"""Input moderation for chatbot queries (mirrors lib/chatbot/content-moderation.ts)."""
from __future__ import annotations

import re

MAX_QUERY_LENGTH = 2000

TOXIC_PATTERNS = [
    re.compile(r"\b(kill\s+yourself|kys|suicide\s+methods?)\b", re.I),
    re.compile(r"\b(r\s*ape|molest|pedoph|child\s+porn)\b", re.I),
    re.compile(r"\b(n[i1]gg[ae]r|f[a4]ggot|ch[i1]nk|k[i1]ke)\b", re.I),
    re.compile(r"\b(fuck|motherfuck|shit|bitch|bastard|cunt|whore|slut)\b", re.I),
    re.compile(r"\b(porn|xxx|hentai|onlyfans)\b", re.I),
    re.compile(r"\b(bomb\s+making|make\s+a\s+bomb|how\s+to\s+kill)\b", re.I),
]

HARASSMENT_PATTERNS = [
    re.compile(r"\b(i\s+will\s+kill\s+you|die\s+bitch|go\s+die)\b", re.I),
    re.compile(r"\b(stupid\s+idiot|dumb\s+ass)\b", re.I),
]

PDF_MISS_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"no passages in this pdf matched",
        r"no relevant information found",
        r"couldn't find relevant",
        r"could not find relevant",
        r"not found in (the )?(document|pdf)",
        r"insufficient information",
        r"i cannot find",
        r"i can't find",
        r"unable to find",
        r"not mentioned in",
        r"does not contain",
        r"don't have (enough )?information",
        r"do not have (enough )?information",
    )
]

PDF_MIN_TOP_SCORE = 0.45
PDF_MIN_CONFIDENCE = 0.42


def moderate_user_input(text: str) -> dict[str, str | bool]:
    trimmed = (text or "").strip()
    if not trimmed:
        return {"allowed": False, "reason": "Message cannot be empty."}
    if len(trimmed) > MAX_QUERY_LENGTH:
        return {
            "allowed": False,
            "reason": f"Message is too long (max {MAX_QUERY_LENGTH} characters).",
        }

    normalized = re.sub(r"[^\w\s]", " ", trimmed.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()

    for pattern in TOXIC_PATTERNS + HARASSMENT_PATTERNS:
        if pattern.search(normalized) or pattern.search(trimmed):
            return {
                "allowed": False,
                "reason": (
                    "Your message was blocked because it may contain harmful or "
                    "inappropriate content. Please ask a respectful, study-related question."
                ),
            }

    letters = re.sub(r"[^a-zA-Z]", "", trimmed)
    if len(letters) >= 8:
        upper = sum(1 for c in trimmed if c.isupper())
        if upper / len(letters) > 0.85:
            return {
                "allowed": False,
                "reason": "Your message looks like spam. Please rephrase your question.",
            }

    if re.search(r"(.)\1{6,}", trimmed) or re.search(r"(.{2,})\1{4,}", trimmed, re.I):
        return {
            "allowed": False,
            "reason": "Your message looks like spam. Please rephrase your question.",
        }

    return {"allowed": True}


def is_pdf_answer_relevant(answer: str, confidence: float, top_score: float | None = None) -> bool:
    trimmed = (answer or "").strip()
    if len(trimmed) < 20:
        return False
    if confidence <= 0:
        return False
    if top_score is not None and top_score < PDF_MIN_TOP_SCORE:
        return False
    if confidence < PDF_MIN_CONFIDENCE:
        return False
    return not any(p.search(trimmed) for p in PDF_MISS_PATTERNS)
