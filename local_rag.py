"""
Local vectorless RAG — no API key, no LLM.
- Index: extract PDF text per page (PyPDF2)
- Retrieve: keyword overlap scoring over pages
- Answer: return top matching excerpts (no generative model)
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import PyPDF2

META_INDEX = "_meta.json"
# Below this keyword score, treat PDF as non-matching and allow web fallback
MIN_RELEVANCE_SCORE = 0.45


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def index_pdf_local(pdf_path: str, workspace: Path) -> dict:
    pdf_path = str(Path(pdf_path).resolve())
    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    pages: list[dict] = []
    with open(pdf_path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages, 1):
            pages.append({"page": i, "content": page.extract_text() or ""})

    structure = []
    for p in pages:
        preview = (p["content"][:100] or f"Page {p['page']}").replace("\n", " ").strip()
        structure.append(
            {
                "title": preview or f"Page {p['page']}",
                "physical_index": p["page"],
                "summary": preview,
            }
        )

    doc_id = str(uuid.uuid4())
    doc_name = Path(pdf_path).name
    doc = {
        "id": doc_id,
        "type": "pdf",
        "path": pdf_path,
        "doc_name": doc_name,
        "doc_description": "Local keyword index (no API key required)",
        "page_count": len(pages),
        "structure": structure,
        "pages": pages,
        "indexMode": "local",
    }

    with open(workspace / f"{doc_id}.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    meta = {
        doc_id: {
            "type": "pdf",
            "doc_name": doc_name,
            "doc_description": doc["doc_description"],
            "page_count": len(pages),
            "path": pdf_path,
            "indexMode": "local",
        }
    }
    with open(workspace / META_INDEX, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "docId": doc_id,
        "pageCount": len(pages),
        "docName": doc_name,
        "description": doc["doc_description"],
        "mode": "local",
    }


def _load_doc(workspace: Path, doc_id: str) -> dict:
    path = workspace / f"{doc_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Document not indexed: {doc_id}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _score_pages(pages: list[dict], query: str) -> list[tuple[int, float, str]]:
    q_terms = set(_tokenize(query))
    if not q_terms:
        return []

    query_lower = query.lower()
    scored: list[tuple[int, float, str]] = []

    for p in pages:
        content = p.get("content") or ""
        if not content.strip():
            continue
        terms = _tokenize(content)
        if not terms:
            continue

        matches = sum(1 for t in terms if t in q_terms)
        score = matches / (len(q_terms) + 1)
        if query_lower in content.lower():
            score += 1.5

        # Title/summary boost from first line
        first_line = content.split("\n", 1)[0].lower()
        if any(t in first_line for t in q_terms):
            score += 0.5

        if score > 0:
            scored.append((p["page"], score, content))

    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored


def search_local(workspace: Path, doc_id: str, question: str, top_k: int = 5) -> dict:
    doc = _load_doc(workspace, doc_id)
    scored = _score_pages(doc.get("pages") or [], question)[:top_k]

    results = []
    for page, score, content in scored:
        results.append(
            {
                "chunkId": f"page-{page}",
                "content": content.strip()[:1200],
                "score": round(min(score, 1.0), 3),
                "confidence": round(min(0.5 + score * 0.3, 0.95), 3),
                "pageNumber": page,
            }
        )

    pages_str = ",".join(str(r["pageNumber"]) for r in results)
    return {"results": results, "pages": pages_str, "mode": "local"}


def query_local(workspace: Path, doc_id: str, question: str, max_pages: int = 5) -> dict:
    doc = _load_doc(workspace, doc_id)
    scored = _score_pages(doc.get("pages") or [], question)[:max_pages]

    if not scored:
        return {
            "answer": (
                f'No passages in this PDF matched "{question}". '
                "Try different keywords from the syllabus or chapter titles."
            ),
            "pages": "",
            "confidence": 0.0,
            "topScore": 0.0,
            "mode": "local",
        }

    top_score = scored[0][1]
    if top_score < MIN_RELEVANCE_SCORE:
        return {
            "answer": (
                f'No passages in this PDF matched "{question}". '
                "Try different keywords from the syllabus or chapter titles."
            ),
            "pages": "",
            "confidence": 0.0,
            "topScore": round(top_score, 3),
            "mode": "local",
        }

    excerpts = []
    for page, _score, content in scored:
        snippet = content.strip()
        if len(snippet) > 900:
            snippet = snippet[:900] + "…"
        excerpts.append(f"### Page {page}\n\n{snippet}")

    pages_str = ",".join(str(s[0]) for s in scored)
    confidence = min(0.95, 0.35 + top_score * 0.25)

    answer = (
        "_Relevant passages from your document (keyword search — no AI API used):_\n\n"
        + "\n\n---\n\n".join(excerpts)
    )

    return {
        "answer": answer,
        "pages": pages_str,
        "confidence": round(confidence, 3),
        "topScore": round(top_score, 3),
        "mode": "local",
    }
