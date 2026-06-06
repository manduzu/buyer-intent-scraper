"""Pluggable search backends used to run dork-style queries.

The default backend uses DuckDuckGo (via the ``ddgs`` package), which needs no
API key. If ``SERPAPI_API_KEY`` is set, the SerpAPI backend (Google results) is
used instead for higher quality / quota.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol

import requests

from buyer_intent_scraper.models import SearchResult

logger = logging.getLogger(__name__)


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Return search results for a raw query string."""
        ...


class DuckDuckGoBackend:
    """Keyless backend using the ``ddgs`` library."""

    name = "duckduckgo"

    def __init__(self, pause: float = 1.0) -> None:
        self.pause = pause

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except ImportError:  # pragma: no cover - exercised only without dep
            logger.error("ddgs is not installed; cannot run DuckDuckGo searches")
            return []

        results: list[SearchResult] = []
        try:
            with DDGS() as ddgs:
                for hit in ddgs.text(query, max_results=max_results):
                    results.append(
                        SearchResult(
                            title=hit.get("title", "") or "",
                            url=hit.get("href", "") or hit.get("url", "") or "",
                            snippet=hit.get("body", "") or "",
                            source_type="search",
                            source_name=self.name,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 - network/backends are flaky
            logger.warning("DuckDuckGo search failed for %r: %s", query, exc)
        finally:
            time.sleep(self.pause)
        return [r for r in results if r.url]


class SerpApiBackend:
    """Google results via SerpAPI (requires ``SERPAPI_API_KEY``)."""

    name = "serpapi"

    def __init__(self, api_key: str, pause: float = 0.5) -> None:
        self.api_key = api_key
        self.pause = pause

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "q": query,
                    "engine": "google",
                    "num": str(max_results),
                    "api_key": self.api_key,
                },
                timeout=30,
            )
            resp.raise_for_status()
            for hit in resp.json().get("organic_results", [])[:max_results]:
                results.append(
                    SearchResult(
                        title=hit.get("title", "") or "",
                        url=hit.get("link", "") or "",
                        snippet=hit.get("snippet", "") or "",
                        source_type="search",
                        source_name=self.name,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SerpAPI search failed for %r: %s", query, exc)
        finally:
            time.sleep(self.pause)
        return [r for r in results if r.url]


def get_search_backend() -> SearchBackend:
    """Return the best available backend based on the environment."""
    api_key = os.environ.get("SERPAPI_API_KEY")
    if api_key:
        logger.info("Using SerpAPI search backend")
        return SerpApiBackend(api_key=api_key)
    logger.info("Using DuckDuckGo search backend (no SERPAPI_API_KEY set)")
    return DuckDuckGoBackend()
