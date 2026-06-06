"""Public tender / procurement portal source.

Searches are restricted to a configurable list of public procurement portal
domains (e.g. Kenya's ``tenders.go.ke``). This finds open tenders / RFQs that
match the requested service, which are strong buyer-intent signals.
"""

from __future__ import annotations

import logging

from buyer_intent_scraper.models import SearchResult
from buyer_intent_scraper.query import ServiceQuery
from buyer_intent_scraper.search import SearchBackend, get_search_backend
from buyer_intent_scraper.sources.base import build_dork, dedupe_results

logger = logging.getLogger(__name__)

# Sensible defaults; override via config.yaml ``tender_portals``.
DEFAULT_TENDER_PORTALS: list[str] = [
    "tenders.go.ke",
    "ppip.go.ke",
    "tendersonline.co.ke",
    "globaltenders.com",
    "tendersinfo.com",
    "constructionreviewonline.com",
]

# Tender-specific phrases worth combining with the service term.
TENDER_TERMS: list[str] = [
    "tender",
    "request for quotation",
    "expression of interest",
    "invitation to bid",
]


class TenderPortalSource:
    name = "tender_portal"

    def __init__(
        self,
        portals: list[str] | None = None,
        backend: SearchBackend | None = None,
        results_per_dork: int = 6,
    ) -> None:
        self.portals = portals if portals is not None else list(DEFAULT_TENDER_PORTALS)
        self.backend = backend or get_search_backend()
        self.results_per_dork = results_per_dork

    def collect(self, query: ServiceQuery, max_results: int = 10) -> list[SearchResult]:
        results: list[SearchResult] = []
        term = TENDER_TERMS[1] if query.intent_keywords else "tender"
        for portal in self.portals:
            dork = build_dork(query.service, query.location, term, site=portal)
            logger.info("[tender_portal] %s", dork)
            for r in self.backend.search(dork, max_results=self.results_per_dork):
                results.append(
                    SearchResult(
                        title=r.title,
                        url=r.url,
                        snippet=r.snippet,
                        source_type=self.name,
                        source_name=portal,
                    )
                )
        return dedupe_results(results)[:max_results]
