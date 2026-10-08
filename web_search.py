"""Web search for chatbot (HTML DuckDuckGo + instant API + Wikipedia)."""
from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

LINK_RE = re.compile(
    r'class="result__a"[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>',
    re.I,
)
SNIP_RE = re.compile(
    r'class="result__snippet"[^>]*>([\s\S]*?)</a>',
    re.I,
)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(re.sub(r"\s+", " ", text).strip())


def _normalize_url(href: str) -> str:
    url = (href or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    try:
        parsed = urlparse(url)
        if "duckduckgo.com" in parsed.netloc and parsed.query:
            qs = parse_qs(parsed.query)
            if qs.get("uddg"):
                return unquote(qs["uddg"][0])
        return url
    except Exception:  # noqa: BLE001
        return url


def _link_label(url: str, fallback: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host.removeprefix("www.") or fallback
    except Exception:  # noqa: BLE001
        return fallback


def _dedupe(hits: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for hit in hits:
        key = (hit.get("url") or hit.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


async def search_duckduckgo_html(query: str, max_results: int = 5) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": USER_AGENT,
                },
            )
            resp.raise_for_status()
            page = resp.text
    except Exception as exc:  # noqa: BLE001
        print(f"[web] DuckDuckGo HTML failed: {exc}")
        return []

    blocks = re.split(r'class="result results_links', page)[1:]

    for block in blocks:
        if len(results) >= max_results:
            break
        if re.search(r"result--ad|result--pla", block, re.I):
            continue

        link_match = LINK_RE.search(block)
        if not link_match:
            continue

        url = _normalize_url(link_match.group(1))
        if not url or re.search(r"ad_domain|/y\.js\?", url, re.I):
            continue

        snip_match = SNIP_RE.search(block)
        title = _strip_html(link_match.group(2))
        snippet = _strip_html(snip_match.group(1) if snip_match else title)
        if not title and not snippet:
            continue
        results.append(
            {
                "title": title or _link_label(url, "Web result"),
                "snippet": snippet or title,
                "url": url,
            }
        )
    return results


def _flatten_related(topics: list) -> list[dict]:
    flat: list[dict] = []
    for topic in topics or []:
        if not isinstance(topic, dict):
            continue
        if isinstance(topic.get("Topics"), list):
            flat.extend(_flatten_related(topic["Topics"]))
        elif topic.get("Text"):
            flat.append(topic)
    return flat


async def search_duckduckgo_instant(query: str, max_results: int = 5) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_redirect": "1"},
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[web] DuckDuckGo instant failed: {exc}")
        return []

    if data.get("Answer"):
        results.append(
            {
                "title": "Instant Answer",
                "snippet": str(data["Answer"]),
                "url": data.get("AnswerURL") or "",
            }
        )
    if data.get("AbstractText") and len(results) < max_results:
        results.append(
            {
                "title": data.get("AbstractHeading") or "Summary",
                "snippet": str(data["AbstractText"]),
                "url": data.get("AbstractURL") or "",
            }
        )
    for topic in _flatten_related(data.get("RelatedTopics") or []):
        if len(results) >= max_results:
            break
        text = topic.get("Text")
        if not text:
            continue
        url = topic.get("FirstURL") or ""
        results.append(
            {
                "title": _link_label(url, "Related topic"),
                "snippet": str(text),
                "url": url,
            }
        )
    return _dedupe(results)[:max_results]


async def search_wikipedia(query: str, max_results: int = 3) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": max_results,
                    "format": "json",
                    "origin": "*",
                },
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            _query, titles, descriptions, urls = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[web] Wikipedia failed: {exc}")
        return []

    hits: list[dict[str, str]] = []
    for i, title in enumerate(titles or []):
        if len(hits) >= max_results:
            break
        url = (urls[i] if i < len(urls) else "") or ""
        if not title or not url:
            continue
        desc = descriptions[i] if i < len(descriptions) else ""
        hits.append(
            {
                "title": f"{title} (Wikipedia)",
                "snippet": desc or f"Wikipedia article: {title}",
                "url": url,
            }
        )
    return hits


async def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    results = await search_duckduckgo_html(query, max_results)
    if len(results) >= max_results:
        return results[:max_results]

    instant = await search_duckduckgo_instant(query, max_results)
    results = _dedupe(results + instant)[:max_results]
    if len(results) >= max_results:
        return results

    wiki = await search_wikipedia(query, max_results - len(results))
    return _dedupe(results + wiki)[:max_results]


async def expanded_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    results = await search_web(query, max_results)
    if results:
        return results
    if '"' in query:
        results = await search_web(query.replace('"', ""), max_results)
        if results:
            return results
    words = query.split()
    if len(words) > 4:
        short = " ".join(words[:4])
        results = await search_web(short, max_results)
    return results


async def duckduckgo_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Backward-compatible entry point."""
    return await expanded_search(query, max_results)
