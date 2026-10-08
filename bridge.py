#!/usr/bin/env python3
"""
CLI bridge for the Next.js chatbot.

Modes:
  local — no API key: PyPDF2 index + keyword page retrieval (vectorless, no LLM)
  full  — PageIndex with LLM (needs OPENAI_API_KEY): tree index + LLM Q&A

Usage:
  python bridge.py index --pdf <path> --workspace <dir> [--mode local|full]
  python bridge.py query --workspace <dir> --doc-id <id> --question <text> [--mode local|full]
  python bridge.py search --workspace <dir> --doc-id <id> --question <text> [--top-k 5] [--mode local|full]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

load_dotenv(PROJECT_ROOT / ".env.local")
load_dotenv(PROJECT_ROOT / ".env")

from local_rag import index_pdf_local, query_local, search_local  # noqa: E402


def _emit(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def _fail(message: str, code: int = 1) -> None:
    _emit({"success": False, "error": message})
    sys.exit(code)


def _resolve_mode(explicit: str | None) -> str:
    if explicit in ("local", "full"):
        return explicit
    env_mode = (os.getenv("PAGEINDEX_MODE") or "").strip().lower()
    if env_mode in ("local", "full"):
        return env_mode
    if os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY"):
        return "full"
    return "local"


# ── Full mode (PageIndex + LLM) ─────────────────────────────────────────────

async def _pick_pages(model: str, structure_json: str, question: str) -> str:
    from pageindex.utils import extract_json, llm_acompletion  # noqa: E402

    prompt = f"""Given document structure JSON and a user question, return JSON with page ranges to read.

Structure:
{structure_json[:20000]}

Question: {question}

Reply JSON only: {{"pages": "5-7", "reasoning": "..."}}"""
    raw = await llm_acompletion(model, prompt)
    parsed = extract_json(raw) if raw else {}
    pages = parsed.get("pages") if isinstance(parsed, dict) else None
    return pages.strip() if isinstance(pages, str) and pages else "1-3"


async def _answer_from_pages(model: str, page_content: str, question: str) -> str:
    from pageindex.utils import llm_acompletion  # noqa: E402

    prompt = f"""Answer using ONLY these excerpts. If insufficient, say so.

{page_content[:30000]}

Question: {question}"""
    return (await llm_acompletion(model, prompt)) or ""


async def run_query_full(client, doc_id: str, question: str) -> dict:
    model = client.retrieve_model
    structure = client.get_document_structure(doc_id)
    pages = await _pick_pages(model, structure, question)
    page_content = client.get_page_content(doc_id, pages)
    answer = await _answer_from_pages(model, page_content, question)
    stripped = answer.strip()
    low_confidence = 0.0
    if stripped:
        low_markers = (
            "insufficient",
            "not found in",
            "cannot find",
            "can't find",
            "unable to find",
            "does not contain",
            "don't have",
            "do not have",
        )
        if any(m in stripped.lower() for m in low_markers):
            low_confidence = 0.0
        else:
            low_confidence = 0.85
    return {
        "success": True,
        "answer": stripped,
        "pages": pages,
        "confidence": low_confidence,
        "mode": "full",
    }


async def run_search_full(client, doc_id: str, question: str, top_k: int) -> dict:
    model = client.retrieve_model
    structure = client.get_document_structure(doc_id)
    pages = await _pick_pages(model, structure, question)
    page_content = json.loads(client.get_page_content(doc_id, pages))
    if not isinstance(page_content, list):
        page_content = []

    results = []
    for item in page_content[:top_k]:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if not content:
            continue
        results.append(
            {
                "chunkId": f"page-{item.get('page', len(results) + 1)}",
                "content": content[:1200],
                "score": 0.9,
                "confidence": 0.85,
                "pageNumber": item.get("page"),
            }
        )
    return {"success": True, "results": results, "pages": pages, "mode": "full"}


def cmd_index(args: argparse.Namespace) -> None:
    pdf_path = Path(args.pdf).resolve()
    workspace = Path(args.workspace).resolve()
    if not pdf_path.is_file():
        _fail(f"PDF not found: {pdf_path}")

    mode = _resolve_mode(args.mode)

    if mode == "local":
        result = index_pdf_local(str(pdf_path), workspace)
        _emit({"success": True, **result})
        return

    from pageindex import PageIndexClient  # noqa: E402

    client = PageIndexClient(api_key=args.api_key or None, workspace=str(workspace))
    doc_id = client.index(str(pdf_path), mode="pdf")
    doc_meta = json.loads(client.get_document(doc_id))
    _emit(
        {
            "success": True,
            "docId": doc_id,
            "docName": doc_meta.get("doc_name") or pdf_path.name,
            "pageCount": doc_meta.get("page_count") or 0,
            "description": doc_meta.get("doc_description") or "",
            "mode": "full",
        }
    )


def cmd_query(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    mode = _resolve_mode(args.mode)

    if mode == "local":
        result = query_local(workspace, args.doc_id, args.question)
        _emit({"success": True, **result})
        return

    from pageindex import PageIndexClient  # noqa: E402

    client = PageIndexClient(workspace=str(workspace))
    if args.doc_id not in client.documents:
        _fail(f"Document not indexed: {args.doc_id}")
    result = asyncio.run(run_query_full(client, args.doc_id, args.question))
    _emit(result)


def cmd_search(args: argparse.Namespace) -> None:
    workspace = Path(args.workspace).resolve()
    mode = _resolve_mode(args.mode)

    if mode == "local":
        result = search_local(workspace, args.doc_id, args.question, args.top_k)
        _emit({"success": True, **result})
        return

    from pageindex import PageIndexClient  # noqa: E402

    client = PageIndexClient(workspace=str(workspace))
    if args.doc_id not in client.documents:
        _fail(f"Document not indexed: {args.doc_id}")
    result = asyncio.run(run_search_full(client, args.doc_id, args.question, args.top_k))
    _emit(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="PageIndex bridge for BtechNotes chatbot")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("index", "query", "search"):
        p = sub.add_parser(name)
        p.add_argument("--mode", choices=("local", "full"), default=None)

    p_index = sub.choices["index"]
    p_index.add_argument("--pdf", required=True)
    p_index.add_argument("--workspace", required=True)
    p_index.add_argument("--api-key", default=None)

    p_query = sub.choices["query"]
    p_query.add_argument("--workspace", required=True)
    p_query.add_argument("--doc-id", required=True)
    p_query.add_argument("--question", required=True)

    p_search = sub.choices["search"]
    p_search.add_argument("--workspace", required=True)
    p_search.add_argument("--doc-id", required=True)
    p_search.add_argument("--question", required=True)
    p_search.add_argument("--top-k", type=int, default=5)

    args = parser.parse_args()
    try:
        if args.command == "index":
            cmd_index(args)
        elif args.command == "query":
            cmd_query(args)
        elif args.command == "search":
            cmd_search(args)
    except Exception as exc:  # noqa: BLE001
        _fail(str(exc))


if __name__ == "__main__":
    main()
