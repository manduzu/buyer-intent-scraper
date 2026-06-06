"""Google/DuckDuckGo dorking source.

Combines the service + location with a rotating set of buyer-intent keywords to
surface pages where someone is *requesting* the service (RFQs, tenders, "looking
for ..." posts, etc.).
"""

from __future__ import annotations

import logging

from buyer_intent_scraper.models import SearchResult
from buyer_intent_scraper.query import ServiceQuery
from buyer_intent_scraper.search import SearchBackend, get_search_backend
from buyer_intent_scraper.sources.base import build_dork, dedupe_results

logger = logging.getLogger(__name__)


class GoogleDorkSource:
    name = "google_dork"

    def __init__(
        self,
        backend: SearchBackend | None = None,
        results_per_dork: int = 8,
        max_dorks: int = 6,
        country_tld: str = "",
    ) -> None:
        self.backend = backend or get_search_backend()
        self.results_per_dork = results_per_dork
        self.max_dorks = max_dorks
        self.country_tld = country_tld.lstrip(".")

    def _dorks(self, query: ServiceQuery) -> list[str]:
        dorks: list[str] = []
        keywords = query.intent_keywords[: self.max_dorks] or [""]
        for kw in keywords:
            dorks.append(build_dork(query.service, query.location, kw))
            if self.country_tld:
                dorks.append(
                    build_dork(query.service, query.location, kw, site=f".{self.country_tld}")
                )
        # Preserve order while de-duplicating identical dork strings.
        seen: set[str] = set()
        unique: list[str] = []
        for d in dorks:
            if d and d not in seen:
                seen.add(d)
                unique.append(d)
        return unique[: self.max_dorks]

    def collect(self, query: ServiceQuery, max_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []
        for dork in self._dorks(query):
            logger.info("[google_dork] %s", dork)
            for r in self.backend.search(dork, max_results=self.results_per_dork):
                results.append(
                    SearchResult(
                        title=r.title,
                        url=r.url,
                        snippet=r.snippet,
                        source_type=self.name,
                        source_name=r.source_name,
                    )
                )
        return dedupe_results(results)[:max_results]
