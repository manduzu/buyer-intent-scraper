"""Common helpers shared by source crawlers."""

from __future__ import annotations

from typing import Protocol

from buyer_intent_scraper.models import SearchResult
from buyer_intent_scraper.query import ServiceQuery


class Source(Protocol):
    """A source crawler produces candidate :class:`SearchResult` pages."""

    name: str

    def collect(self, query: ServiceQuery, max_results: int = 10) -> list[SearchResult]:
        ...


def quote(term: str) -> str:
    """Wrap a multi-word term in quotes for an exact-match dork."""
    term = term.strip()
    if not term:
        return ""
    return f'"{term}"' if " " in term else term


def build_dork(
    service: str,
    location: str,
    intent_keyword: str = "",
    site: str = "",
) -> str:
    """Build a single search-engine dork string."""
    parts: list[str] = []
    if service:
        parts.append(quote(service))
    if intent_keyword:
        parts.append(quote(intent_keyword))
    if location:
        parts.append(quote(location))
    if site:
        parts.append(f"site:{site}")
    return " ".join(p for p in parts if p)


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for r in results:
        key = r.url.split("#")[0].rstrip("/").lower()
        if key and key not in seen:
            seen.add(key)
            out.append(r)
    return out
