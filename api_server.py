"""
Hosted RAG API — upgraded with Vector RAG pipeline, OpenRouter LLM, and Knowledge Graph endpoints.
Run locally:
  pip install -r requirements.txt
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

import os
import json
import shutil
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env.local")
load_dotenv(Path(__file__).resolve().parent / ".env")

from data_storage import (
    ROOT, PDF_DIR, META_DIR, PAGEINDEX_DIR,
    ensure_dirs, get_workspace, save_pdf_bytes,
    save_metadata, load_metadata, delete_all, new_pdf_record
)
from vector_rag import index_pdf_vector, query_vector_rag
from knowledge_graph import generate_and_save_graph, load_graph
from openrouter_client import (
    chat_with_openrouter,
    build_rag_system_prompt,
    get_available_models,
)


API_PREFIX = "/api/chatbot"
app = FastAPI(title="RAG Chat Assistant API", version="2.0.0")

_origins = os.getenv("CORS_ORIGINS", "*").strip()
allow_origins = ["*"] if _origins == "*" else [o.strip() for o in _origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE = 50 * 1024 * 1024


@app.on_event("startup")
def startup() -> None:
    ensure_dirs()


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/health")
@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "service": "rag-chat-assistant",
        "version": "2.0.0",
        "pipeline": "vector_rag",
        "models": len(get_available_models()),
        "openrouter_key_set": bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Models List
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/models")
async def list_models() -> dict:
    return {"models": get_available_models()}


# ─────────────────────────────────────────────────────────────────────────────
# Upload & Index
# ─────────────────────────────────────────────────────────────────────────────

@app.post(f"{API_PREFIX}/upload")
async def upload(
    file: UploadFile = File(...),
    userId: str = Form(default="anon"),
) -> dict:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 50MB limit")

    pdf_id = str(uuid.uuid4())
    file_path = save_pdf_bytes(pdf_id, file.filename, content)
    workspace = get_workspace(pdf_id)
    workspace.mkdir(parents=True, exist_ok=True)

    try:
        indexed = index_pdf_vector(str(file_path), workspace)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Indexing failed: {exc}")

    # Asynchronously build knowledge graph
    try:
        generate_and_save_graph(workspace, indexed["docId"])
    except Exception:
        pass

    record = {
        "id": pdf_id,
        "name": file.filename,
        "size": len(content),
        "uploadedAt": datetime.now(timezone.utc).isoformat(),
        "userId": userId,
        "metadata": {
            "pages": indexed["pageCount"],
            "chunkCount": indexed["chunkCount"],
            "filePath": str(file_path),
            "vectorDocId": indexed["docId"],
            "ragMode": "vector",
        },
    }
    save_metadata(pdf_id, record)

    return {
        "success": True,
        "pdfId": pdf_id,
        "fileName": file.filename,
        "uploadedAt": record["uploadedAt"],
        "totalChunks": indexed["chunkCount"],
        "pages": indexed["pageCount"],
        "ragMode": "vector",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Chat with RAG + OpenRouter
# ─────────────────────────────────────────────────────────────────────────────

class ChatBody(BaseModel):
    pdfId: str
    query: str
    userId: str = "anon"
    model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    topK: int = 4
    apiKey: Optional[str] = None
    chatHistory: Optional[list] = None


@app.post(f"{API_PREFIX}/chat")
async def chat(body: ChatBody) -> dict:
    try:
        meta = load_metadata(body.pdfId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found — please upload it first")

    vector_doc_id = meta["metadata"].get("vectorDocId")
    if not vector_doc_id:
        raise HTTPException(status_code=400, detail="Document not indexed with vector pipeline")

    workspace = get_workspace(body.pdfId)
    doc_name = meta.get("name", "document.pdf")

    # Step 1: Vector similarity retrieval
    chunks = query_vector_rag(workspace, vector_doc_id, body.query, top_k=body.topK)

    if not chunks:
        return {
            "success": True,
            "answer": "I could not find relevant content in the document for your question. Please try rephrasing or upload a more specific document.",
            "sources": [],
            "model": body.model,
        }

    # Step 2: Build system prompt with retrieved chunks
    system_prompt = build_rag_system_prompt(doc_name, chunks)

    # Step 3: Call OpenRouter
    result = await chat_with_openrouter(
        model_id=body.model,
        system_prompt=system_prompt,
        user_message=body.query,
        chat_history=body.chatHistory,
        api_key=body.apiKey,
    )

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "LLM request failed"))

    return {
        "success": True,
        "answer": result["answer"],
        "sources": [
            {"page": c["page"], "score": c["score"], "excerpt": c["text"][:300]}
            for c in chunks
        ],
        "model": body.model,
        "usage": result.get("usage", {}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Graph
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/graph/{{pdf_id}}")
async def get_graph(pdf_id: str) -> dict:
    try:
        meta = load_metadata(pdf_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")

    workspace = get_workspace(pdf_id)
    vector_doc_id = meta["metadata"].get("vectorDocId")
    if not vector_doc_id:
        raise HTTPException(status_code=400, detail="Document not indexed yet")

    graph = load_graph(workspace, vector_doc_id)
    if not graph.get("nodes"):
        graph = generate_and_save_graph(workspace, vector_doc_id)

    return graph


# ─────────────────────────────────────────────────────────────────────────────
# List Documents
# ─────────────────────────────────────────────────────────────────────────────

@app.get(f"{API_PREFIX}/documents")
async def list_documents(userId: str = "anon") -> dict:
    ensure_dirs()
    docs = []
    for meta_file in META_DIR.glob("*.json"):
        try:
            record = json.loads(meta_file.read_text(encoding="utf-8"))
            if record.get("userId") == userId or userId == "anon":
                docs.append({
                    "pdfId": record["id"],
                    "fileName": record["name"],
                    "pages": record["metadata"].get("pages", 0),
                    "chunkCount": record["metadata"].get("chunkCount", 0),
                    "uploadedAt": record.get("uploadedAt", ""),
                    "ragMode": record["metadata"].get("ragMode", "vector"),
                })
        except Exception:
            continue
    return {"documents": sorted(docs, key=lambda x: x["uploadedAt"], reverse=True)}


# ─────────────────────────────────────────────────────────────────────────────
# Delete Document
# ─────────────────────────────────────────────────────────────────────────────

class DeleteBody(BaseModel):
    pdfId: str
    userId: str = "anon"


@app.post(f"{API_PREFIX}/delete")
async def delete_pdf(body: DeleteBody) -> dict:
    try:
        delete_all(body.pdfId)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="PDF not found")
    return {"success": True, "pdfId": body.pdfId}


# ─────────────────────────────────────────────────────────────────────────────
# Web UI
# ─────────────────────────────────────────────────────────────────────────────

UI_DIR = Path(__file__).resolve().parent / "ui"
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)
