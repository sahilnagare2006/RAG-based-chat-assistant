"""
openrouter_client.py
OpenRouter LLM Integration with RAG-grounded system prompt construction.
Supports multiple model tiers via litellm + direct httpx fallback.
"""
from __future__ import annotations

import os
import json
import httpx
from typing import Any, Dict, List, Optional


OPENROUTER_BASE = "https://openrouter.ai/api/v1"

AVAILABLE_MODELS = [
    {
        "id": "deepseek/deepseek-v4-pro",
        "name": "DeepSeek V4 Pro",
        "provider": "DeepSeek",
        "description": "Best for technical deep Q&A and document reasoning",
        "badge": "🔥 Recommended",
        "free": False
    },
    {
        "id": "deepseek/deepseek-v4-flash",
        "name": "DeepSeek V4 Flash",
        "provider": "DeepSeek",
        "description": "Fast and efficient reasoning model",
        "badge": "⚡ Fast",
        "free": False
    },
    {
        "id": "anthropic/claude-sonnet-5.5",
        "name": "Claude Sonnet 5.5",
        "provider": "Anthropic",
        "description": "Best quality for nuanced analysis and synthesis",
        "badge": "🏆 Top Tier",
        "free": False
    },
    {
        "id": "google/gemini-3.8-flash",
        "name": "Gemini 3.8 Flash",
        "provider": "Google",
        "description": "Ultra-fast, enormous context window",
        "badge": "⚡ Ultra-Fast",
        "free": False
    },
    {
        "id": "openai/gpt-5.5",
        "name": "GPT-5.5",
        "provider": "OpenAI",
        "description": "Highly capable general assistant",
        "badge": "🎯 Efficient",
        "free": False
    },
    {
        "id": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "name": "Nemotron 3 Ultra (Free)",
        "provider": "NVIDIA",
        "description": "Powerful free-tier model for testing",
        "badge": "✅ Free",
        "free": True
    },
    {
        "id": "google/gemma-4-31b-it:free",
        "name": "Gemma 4 31B (Free)",
        "provider": "Google",
        "description": "Free Google model for development and testing",
        "badge": "✅ Free",
        "free": True
    },
]


def build_rag_system_prompt(doc_name: str, retrieved_chunks: List[Dict[str, Any]]) -> str:
    """Assembles a RAG-grounded system prompt with document citations."""
    chunk_context = ""
    for i, chunk in enumerate(retrieved_chunks, 1):
        page = chunk.get("page", "?")
        score = chunk.get("score", 0)
        text = chunk.get("text", "").strip()
        chunk_context += f"\n[Source {i} — Page {page} | Relevance: {score:.2f}]\n{text}\n"

    return f"""You are a precise and helpful AI assistant specializing in analyzing the document: "{doc_name}".

Your job is to answer questions grounded STRICTLY in the document excerpts provided below.

RETRIEVED DOCUMENT EXCERPTS:
{chunk_context}

RULES:
1. Base your answer ONLY on the excerpts above. Do NOT use general world knowledge to fill gaps.
2. After each factual claim, insert an inline citation like [Page 3] or [Pages 2-4].
3. If the excerpts do not contain enough information, respond: "The document does not contain sufficient information about this topic."
4. Format your response clearly using markdown: headers, bullet points, code blocks where applicable.
5. Be concise, accurate, and avoid hallucination.
"""


async def chat_with_openrouter(
    model_id: str,
    system_prompt: str,
    user_message: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Sends a chat completion request to the OpenRouter API.
    Returns: { "answer": str, "model": str, "usage": {...} }
    """
    key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY") or ""

    if not key:
        return {
            "success": False,
            "answer": "",
            "error": "No OpenRouter API key configured. Please set OPENROUTER_API_KEY in .env."
        }

    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sahilnagare2006/RAG-based-chat-assistant",
        "X-Title": "RAG Chat Assistant",
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        answer = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {})

        return {
            "success": True,
            "answer": answer,
            "model": model_id,
            "usage": usage,
        }

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("error", {}).get("message", str(e))
        except Exception:
            detail = str(e)
        return {"success": False, "answer": "", "error": f"OpenRouter API error: {detail}"}

    except Exception as e:
        return {"success": False, "answer": "", "error": f"Network error: {str(e)}"}


def get_available_models() -> List[Dict[str, Any]]:
    """Returns the full list of supported OpenRouter models."""
    return AVAILABLE_MODELS
