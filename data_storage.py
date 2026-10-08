"""File + metadata storage for the hosted RAG API."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.getenv("RAG_DATA_DIR", Path(__file__).resolve().parent / "data")).resolve()
PDF_DIR = ROOT / "pdfs"
META_DIR = ROOT / "metadata"
PAGEINDEX_DIR = ROOT / "pageindex"

MAX_FILE_SIZE = 50 * 1024 * 1024


def ensure_dirs() -> None:
    for d in (PDF_DIR, META_DIR, PAGEINDEX_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _meta_path(pdf_id: str) -> Path:
    return META_DIR / f"{pdf_id}.json"


def save_pdf_bytes(pdf_id: str, filename: str, content: bytes) -> Path:
    ensure_dirs()
    safe = re.sub(r"[^a-zA-Z0-9.-]", "_", filename)
    path = PDF_DIR / f"{pdf_id}-{safe}"
    path.write_bytes(content)
    return path


def save_metadata(pdf_id: str, record: dict[str, Any]) -> None:
    ensure_dirs()
    _meta_path(pdf_id).write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")


def load_metadata(pdf_id: str) -> dict[str, Any]:
    path = _meta_path(pdf_id)
    if not path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def delete_all(pdf_id: str) -> None:
    meta = load_metadata(pdf_id)
    file_path = Path(meta.get("metadata", {}).get("filePath", ""))
    if file_path.is_file():
        file_path.unlink(missing_ok=True)
    _meta_path(pdf_id).unlink(missing_ok=True)
    workspace = PAGEINDEX_DIR / pdf_id
    if workspace.is_dir():
        shutil.rmtree(workspace, ignore_errors=True)


def new_pdf_record(
    pdf_id: str,
    name: str,
    size: int,
    user_id: str,
    file_path: Path,
    *,
    page_count: int,
    page_index_doc_id: str,
    description: str,
    rag_mode: str,
) -> dict[str, Any]:
    return {
        "id": pdf_id,
        "name": name,
        "size": size,
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "userId": user_id,
        "chunks": [],
        "metadata": {
            "pages": page_count,
            "filePath": str(file_path),
            "extractedAt": datetime.now(timezone.utc).isoformat(),
            "pageIndexDocId": page_index_doc_id,
            "pageIndexReady": True,
            "pageIndexDescription": description,
            "ragMode": rag_mode,
        },
    }


def get_workspace(pdf_id: str) -> Path:
    return PAGEINDEX_DIR / pdf_id
