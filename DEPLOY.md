# Deploy RAG API separately from Vercel

Split architecture:

| Layer | Platform | Role |
|-------|----------|------|
| **Frontend** | Vercel | Next.js UI (`/chatbot`, subjects, admin UI) |
| **RAG API** | Render / Railway / Fly.io / VPS | Python `api_server.py` + PDF storage |

Vercel **cannot** run long Python PDF indexing reliably. Host `rag_chatbot` on a service with a **persistent disk** and longer timeouts.

---

## 1. Deploy the RAG API

### Option A — Docker (Render, Railway, Fly.io)

```bash
cd rag_chatbot
docker build -t btechnotes-rag .
docker run -p 8000:8000 -v rag-data:/data \
  -e PAGEINDEX_MODE=local \
  -e CORS_ORIGINS=https://your-app.vercel.app \
  btechnotes-rag
```

### Option B — Render web service

1. New **Web Service** → connect repo (or deploy `rag_chatbot` folder).
2. **Root directory:** `rag_chatbot`
3. **Build:** `pip install -r requirements.txt`
4. **Start:** `uvicorn api_server:app --host 0.0.0.0 --port $PORT`
5. Add **disk** mount at `/data`, env `RAG_DATA_DIR=/data`
6. Env vars:
   - `CORS_ORIGINS=https://your-app.vercel.app,https://www.your-domain.com`
   - `PAGEINDEX_MODE=local` (no API key) or `full` + `OPENAI_API_KEY`
   - Optional: `RAG_API_SECRET` for `X-RAG-API-Key` header

Your API base URL will be like: `https://btechnotes-rag.onrender.com`

---

## 2. Configure Vercel (frontend only)

In **Vercel → Project → Environment Variables** (recommended — same-origin, no CORS):

```env
CHATBOT_RAG_API_BASE_URL=https://btechnotes-chat.onrender.com
RAG_API_SECRET=your-secret-if-set-on-rag-host
```

Redeploy Vercel. Next.js routes under `/api/chatbot/*` **proxy** to the RAG host for `upload`, `chat`, `search`, `extract`, `delete`, `websearch`.

**Alternative:** set `NEXT_PUBLIC_CHATBOT_API_BASE_URL=https://btechnotes-rag.onrender.com/api/chatbot` so the browser calls Render directly (requires `CORS_ORIGINS` on the RAG host).

Leave both empty for local dev (same-origin `/api/chatbot` + Python on your machine).

---

## 3. CORS

The RAG host must allow your Vercel origin:

```env
CORS_ORIGINS=https://your-app.vercel.app
```

Use `*` only for testing.

---

## 4. Optional API key (recommended in production)

On the RAG host:

```env
RAG_API_SECRET=your-long-random-secret
```

If set, every request needs header: `X-RAG-API-Key: your-long-random-secret`.

Because the browser cannot hold secrets in `NEXT_PUBLIC_*`, use either:

- **Public RAG API** + CORS allowlist only (simpler), or
- **Vercel proxy routes** that add the header server-side (not included by default).

---

## 5. What stays on Vercel

- Main site pages and admin (Firebase)
- Optional: keep `app/api/chatbot/*` for local dev only

Production chatbot traffic should go **directly** to the RAG host via `NEXT_PUBLIC_CHATBOT_API_BASE_URL`.

---

## 6. Health check

```bash
curl https://your-rag-host.com/api/chatbot/health
```

Expect: `{"ok":true,"service":"btechnotes-rag","ragMode":"local",...}`
