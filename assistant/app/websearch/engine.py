from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class PageExtract:
    url: str
    title: str
    text: str


def web_search(query: str, max_results: int = 6) -> list[SearchHit]:
    """Free web search via duckduckgo (no API key)."""
    try:
        from ddgs import DDGS
    except ImportError:  # pragma: no cover
        from duckduckgo_search import DDGS  # type: ignore

    hits: list[SearchHit] = []
    with DDGS() as ddgs:
        for row in ddgs.text(query, region="ru-ru", max_results=max_results):
            hits.append(
                SearchHit(
                    title=str(row.get("title") or ""),
                    url=str(row.get("href") or row.get("link") or ""),
                    snippet=str(row.get("body") or row.get("snippet") or ""),
                )
            )
    return [h for h in hits if h.url]


async def fetch_page_text(url: str, timeout: float = 12.0, limit: int = 4000) -> PageExtract:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:  # noqa: BLE001
        log.info("fetch failed %s: %s", url, exc)
        return PageExtract(url=url, title="", text="")

    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = WS_RE.sub(" ", TAG_RE.sub("", title_m.group(1))).strip() if title_m else ""
    # drop scripts/styles
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.I)
    text = WS_RE.sub(" ", TAG_RE.sub(" ", cleaned)).strip()
    return PageExtract(url=url, title=title, text=text[:limit])


async def gather_research(
    query: str,
    *,
    max_results: int = 6,
    fetch_top: int = 3,
) -> tuple[list[SearchHit], list[PageExtract]]:
    hits = web_search(query, max_results=max_results)
    pages: list[PageExtract] = []
    for hit in hits[:fetch_top]:
        pages.append(await fetch_page_text(hit.url))
    return hits, pages


def format_research_context(
    query: str, hits: list[SearchHit], pages: list[PageExtract]
) -> str:
    lines = [
        f"Запрос пользователя: {query}",
        "",
        "Результаты поиска:",
    ]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {h.title}")
        lines.append(f"   URL: {h.url}")
        if h.snippet:
            lines.append(f"   {h.snippet}")
    if pages:
        lines.append("")
        lines.append("Фрагменты страниц:")
        for p in pages:
            if not p.text:
                continue
            lines.append(f"— {p.title or p.url}")
            lines.append(p.url)
            lines.append(p.text[:1800])
            lines.append("")
    return "\n".join(lines)
