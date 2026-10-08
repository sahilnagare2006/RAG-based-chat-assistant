"""Business logic for the hosted RAG API (mirrors Next.js chatbot services)."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from data_storage import (
    MAX_FILE_SIZE,
    delete_all,
    get_workspace,
    load_metadata,
    new_pdf_record,
    save_metadata,
    save_pdf_bytes,
)
from content_moderation import is_pdf_answer_relevant, moderate_user_input
from local_rag import index_pdf_local, query_local, search_local
from web_search import duckduckgo_search


def resolve_rag_mode() -> str:
    explicit = (os.getenv("PAGEINDEX_MODE") or "").strip().lower()
    if explicit in ("local", "full"):
        return explicit
    if os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY"):
        return "full"
    return "local"


def clean_search_query(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", (query or "").strip())
    return cleaned[:500]


def is_valid_search_query(query: str) -> bool:
    return len(clean_search_query(query)) >= 2


def _index_full(pdf_path: str, workspace: Path) -> dict[str, Any]:
    from pageindex import PageIndexClient  # lazy import — heavy deps

    client = PageIndexClient(workspace=str(workspace))
    doc_id = client.index(pdf_path, mode="pdf")
    import json

    doc_meta = json.loads(client.get_document(doc_id))
    return {
        "docId": doc_id,
        "pageCount": doc_meta.get("page_count") or 0,
        "docName": doc_meta.get("doc_name") or Path(pdf_path).name,
        "description": doc_meta.get("doc_description") or "",
        "mode": "full",
    }


async def handle_upload(file_bytes: bytes, filename: str, user_id: str) -> dict[str, Any]:
    if not user_id:
        return {"success": False, "error": "User ID is required"}
    if not filename.lower().endswith(".pdf"):
        return {"success": False, "error": "Only PDF files are allowed"}
    if len(file_bytes) > MAX_FILE_SIZE:
        return {"success": False, "error": f"File size exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB"}

    pdf_id = str(uuid.uuid4())
    file_path = save_pdf_bytes(pdf_id, filename, file_bytes)
    workspace = get_workspace(pdf_id)
    mode = resolve_rag_mode()

    try:
        if mode == "local":
            indexed = index_pdf_local(str(file_path), workspace)
        else:
            indexed = _index_full(str(file_path), workspace)
    except Exception as exc:  # noqa: BLE001
        delete_all(pdf_id)
        return {"success": False, "error": str(exc)}

    record = new_pdf_record(
        pdf_id,
        filename,
        len(file_bytes),
        user_id,
        file_path,
        page_count=indexed["pageCount"],
        page_index_doc_id=indexed["docId"],
        description=indexed.get("description") or "",
        rag_mode=indexed.get("mode") or mode,
    )
    save_metadata(pdf_id, record)

    return {
        "success": True,
        "pdfId": pdf_id,
        "fileName": filename,
        "uploadedAt": record["uploadedAt"],
        "totalChunks": indexed["pageCount"],
        "size": len(file_bytes),
        "pages": indexed["pageCount"],
        "ragMode": record["metadata"]["ragMode"],
    }


def _query_indexed(pdf_id: str, doc_id: str, question: str, rag_mode: str) -> dict[str, Any]:
    workspace = get_workspace(pdf_id)
    if rag_mode == "full":
        import asyncio
        from bridge import run_query_full  # noqa: WPS433
        from pageindex import PageIndexClient

        client = PageIndexClient(workspace=str(workspace))
        result = asyncio.run(run_query_full(client, doc_id, question))
        return {
            "answer": result.get("answer", ""),
            "pages": result.get("pages", ""),
            "confidence": result.get("confidence", 0.0),
        }
    result = query_local(workspace, doc_id, question)
    return {
        "answer": result["answer"],
        "pages": result["pages"],
        "confidence": result["confidence"],
    }


def _search_indexed(pdf_id: str, doc_id: str, question: str, top_k: int, rag_mode: str) -> dict:
    workspace = get_workspace(pdf_id)
    if rag_mode == "full":
        import asyncio
        from bridge import run_search_full
        from pageindex import PageIndexClient

        client = PageIndexClient(workspace=str(workspace))
        return asyncio.run(run_search_full(client, doc_id, question, top_k))
    return search_local(workspace, doc_id, question, top_k)


def _format_pdf_response(content: str, confidence: float, pages: str, rag_mode: str) -> str:
    pct = f"{confidence * 100:.1f}"
    page_note = f"\n\n_(Source pages: {pages})_" if pages else ""
    mode_note = (
        "\n\n_(Keyword search over your PDF — no AI API used.)_"
        if rag_mode == "local"
        else ""
    )
    return f"**Based on your document** · Confidence: {pct}%\n\n{content}{page_note}{mode_note}"


def _link_label(url: str, fallback: str) -> str:
    if not url:
        return fallback
    try:
        from urllib.parse import urlparse

        host = urlparse(url).hostname or ""
        return host.removeprefix("www.") or fallback
    except Exception:  # noqa: BLE001
        return fallback


def _format_web_response(
    results: list[dict[str, str]], query: str, *, explicit: bool = False
) -> dict[str, Any]:
    items = [r for r in results if (r.get("snippet") or "").strip()]
    if not items:
        return {
            "markdown": f'I couldn\'t find web results for **"{query}"**. Try different keywords.',
            "webUrls": [],
        }

    web_urls = [r.get("url") or "" for r in items if r.get("url")]
    sections = []
    for i, item in enumerate(items):
        url = item.get("url") or ""
        label = (item.get("title") or "").strip() or _link_label(url, f"Source {i + 1}")
        heading = f"[{label}]({url})" if url else f"**{label}**"
        sections.append(f"### {heading}\n\n{item.get('snippet', '').strip()}")

    header = (
        f'**Web search** · results for **"{query}"**:'
        if explicit
        else f'**Not found in your PDF** — here are web results for **"{query}"**:'
    )
    markdown = (
        f"{header}\n\n"
        + "\n\n---\n\n".join(sections)
        + "\n\n_Sources: DuckDuckGo. Verify facts before exams._"
    )
    return {"markdown": markdown, "webUrls": web_urls, "primaryUrl": web_urls[0] if web_urls else None}


async def _respond_web(cleaned: str, *, explicit: bool) -> dict[str, Any]:
    try:
        web = await duckduckgo_search(cleaned, 5)
        if web:
            formatted = _format_web_response(web, cleaned, explicit=explicit)
            return {
                "success": True,
                "messageId": str(uuid.uuid4()),
                "response": formatted["markdown"],
                "source": "web",
                "confidence": 0.5,
                "webUrl": formatted.get("primaryUrl"),
                "webUrls": formatted.get("webUrls") or [],
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] web search failed: {exc}")

    return {
        "success": True,
        "messageId": str(uuid.uuid4()),
        "response": f'I couldn\'t find web results for **"{cleaned}"**. Try different keywords.',
        "confidence": 0,
    }


async def handle_chat(
    pdf_id: str, query: str, user_id: str, *, web_search_only: bool = False
) -> dict[str, Any]:
    if not pdf_id or not query or not user_id:
        return {"success": False, "error": "pdfId, query, and userId are required"}

    moderation = moderate_user_input(query)
    if not moderation.get("allowed"):
        return {"success": False, "error": moderation.get("reason")}

    cleaned = clean_search_query(query)
    if not is_valid_search_query(cleaned):
        return {"success": False, "error": "Query is too short or invalid"}

    try:
        record = load_metadata(pdf_id)
    except FileNotFoundError:
        return {"success": False, "error": "PDF not found"}

    meta = record.get("metadata", {})
    doc_id = meta.get("pageIndexDocId")
    rag_mode = meta.get("ragMode") or resolve_rag_mode()

    if not meta.get("pageIndexReady") or not doc_id:
        return {"success": False, "error": "PDF is not indexed. Please re-upload."}

    if web_search_only:
        return await _respond_web(cleaned, explicit=True)

    try:
        result = _query_indexed(pdf_id, doc_id, cleaned, rag_mode)
        answer = (result.get("answer") or "").strip()
        confidence = float(result.get("confidence", 0) or 0)
        top_score = result.get("topScore")
        if is_pdf_answer_relevant(answer, confidence, top_score):
            return {
                "success": True,
                "messageId": str(uuid.uuid4()),
                "response": _format_pdf_response(
                    answer, confidence, result.get("pages", ""), rag_mode
                ),
                "source": "pdf",
                "confidence": confidence,
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] RAG query failed: {exc}")

    return {
        "success": True,
        "messageId": str(uuid.uuid4()),
        "response": (
            f'I couldn\'t find relevant information about **"{cleaned}"** in your PDF. '
            "Turn on **Web search** in the input bar to look online, or try different keywords."
        ),
        "confidence": 0,
        "source": "pdf",
    }


async def handle_search(pdf_id: str, query: str, top_k: int = 5) -> dict[str, Any]:
    if not pdf_id:
        return {"success": False, "error": "PDF ID is required"}
    if not query:
        return {"success": False, "error": "Query is required"}

    cleaned = clean_search_query(query)
    if not is_valid_search_query(cleaned):
        return {"success": False, "error": "Query is too short or invalid"}

    try:
        record = load_metadata(pdf_id)
    except FileNotFoundError:
        return {"success": False, "error": "PDF not found"}

    meta = record.get("metadata", {})
    doc_id = meta.get("pageIndexDocId")
    rag_mode = meta.get("ragMode") or resolve_rag_mode()

    if not meta.get("pageIndexReady") or not doc_id:
        return {"success": False, "error": "PDF is not indexed. Re-upload the file."}

    try:
        raw = _search_indexed(pdf_id, doc_id, cleaned, top_k, rag_mode)
        results = raw.get("results") or []
        return {
            "success": True,
            "results": [
                {
                    "chunkId": r.get("chunkId"),
                    "content": r.get("content"),
                    "score": r.get("score", 0),
                    "confidence": r.get("confidence", 0),
                    "pageNumber": r.get("pageNumber"),
                }
                for r in results
            ],
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}


def handle_extract(pdf_id: str) -> dict[str, Any]:
    if not pdf_id:
        return {"success": False, "error": "PDF ID is required"}
    try:
        record = load_metadata(pdf_id)
    except FileNotFoundError:
        return {"success": False, "error": "PDF not found"}

    meta = record.get("metadata", {})
    doc_id = meta.get("pageIndexDocId")
    workspace = get_workspace(pdf_id)
    structure_preview = None
    if doc_id:
        doc_path = workspace / f"{doc_id}.json"
        if doc_path.is_file():
            import json

            doc = json.loads(doc_path.read_text(encoding="utf-8"))
            structure = doc.get("structure") or []
            structure_preview = structure[:5] if isinstance(structure, list) else structure

    return {
        "success": True,
        "pdfId": record["id"],
        "fileName": record["name"],
        "pageIndex": {
            "docId": doc_id,
            "ready": bool(meta.get("pageIndexReady")),
            "description": meta.get("pageIndexDescription"),
            "structurePreview": structure_preview,
            "ragMode": meta.get("ragMode"),
        },
        "stats": {"totalPages": meta.get("pages", 0)},
    }


def handle_delete(pdf_id: str, user_id: str) -> dict[str, Any]:
    if not pdf_id or not user_id:
        return {"success": False, "error": "pdfId and userId are required"}
    try:
        record = load_metadata(pdf_id)
        if record.get("userId") != user_id:
            return {"success": False, "error": "Unauthorized to delete this PDF"}
        delete_all(pdf_id)
    except FileNotFoundError:
        pass  # already deleted (duplicate cleanup)
    return {"success": True}


async def handle_websearch(query: str, max_results: int = 3) -> dict[str, Any]:
    if not query:
        return {"success": False, "query": query, "error": "Query is required"}

    moderation = moderate_user_input(query)
    if not moderation.get("allowed"):
        return {"success": False, "query": query, "error": moderation.get("reason")}

    cleaned = clean_search_query(query)
    if not is_valid_search_query(cleaned):
        return {"success": False, "query": cleaned, "error": "Query is too short or invalid"}
    try:
        results = await duckduckgo_search(cleaned, max_results)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "query": cleaned, "error": str(exc)}
    if not results:
        return {"success": False, "query": cleaned, "error": "No search results found"}
    return {
        "success": True,
        "query": cleaned,
        "results": [
            {
                "title": r.get("title", f"Result {i + 1}"),
                "snippet": r["snippet"],
                "url": r.get("url", ""),
                "score": 1.0 - i * 0.1,
            }
            for i, r in enumerate(results)
        ],
        "snippet": results[0]["snippet"],
        "url": results[0].get("url"),
        "source": "DuckDuckGo",
    }
