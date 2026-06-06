"""B2B directory & classifieds source.

Searches are restricted to a configurable list of business directory / classifieds
domains. These surface businesses and individuals advertising that they want a
service, plus listings that carry public contact details.
"""

from __future__ import annotations

import logging

from buyer_intent_scraper.models import SearchResult
from buyer_intent_scraper.query import ServiceQuery
from buyer_intent_scraper.search import SearchBackend, get_search_backend
from buyer_intent_scraper.sources.base import build_dork, dedupe_results

logger = logging.getLogger(__name__)

# Sensible defaults (Kenya/EA-leaning); override via config.yaml ``directories``.
DEFAULT_DIRECTORIES: list[str] = [
    "yellowpageskenya.com",
    "businesslist.co.ke",
    "vipkenya.com",
    "kenyaplex.com",
    "jiji.co.ke",
    "pigiame.co.ke",
    "brabys.com",
]

DIRECTORY_TERMS: list[str] = [
    "looking for",
    "request",
    "needed",
    "wanted",
]


class DirectorySource:
    name = "directory"

    def __init__(
        self,
        directories: list[str] | None = None,
        backend: SearchBackend | None = None,
        results_per_dork: int = 6,
    ) -> None:
        self.directories = (
            directories if directories is not None else list(DEFAULT_DIRECTORIES)
        )
        self.backend = backend or get_search_backend()
        self.results_per_dork = results_per_dork

    def collect(self, query: ServiceQuery, max_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []
        term = DIRECTORY_TERMS[0]
        for directory in self.directories:
            dork = build_dork(query.service, query.location, term, site=directory)
            logger.info("[directory] %s", dork)
            for r in self.backend.search(dork, max_results=self.results_per_dork):
                results.append(
                    SearchResult(
                        title=r.title,
                        url=r.url,
                        snippet=r.snippet,
                        source_type=self.name,
                        source_name=directory,
                    )
                )
        return dedupe_results(results)[:max_results]
