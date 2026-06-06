"""Kenya PPIP (tenders.go.ke) procurement-notices source.

Kenya's Public Procurement Information Portal exposes its **active** tenders
through a public JSON API (``/api/active-tenders``). Each record already carries
the procuring entity (the buyer), its contact email/phone, the closing date and
a reference number, so this source yields fully-formed :class:`Lead` objects
directly -- the same structured pattern as the World Bank source, but Kenya
specific and keyless.

Note: the portal's TLS certificate is frequently expired upstream, so requests
are made with certificate verification disabled (the data itself is public).
"""

from __future__ import annotations

import logging

import requests
import urllib3

from buyer_intent_scraper.extract import classify_entity, extract_emails, extract_phones
from buyer_intent_scraper.models import Lead
from buyer_intent_scraper.query import ServiceQuery

logger = logging.getLogger(__name__)

API_URL = "https://tenders.go.ke/api/active-tenders"
DETAIL_URL = "https://tenders.go.ke/tenders/{id}"
PAGE_SIZE = 10  # the API ignores per_page; it always returns 10 rows/page

# Generic words that shouldn't be used as the title search keyword.
_GENERIC_TERMS = {
    "services",
    "service",
    "works",
    "work",
    "supply",
    "provision",
    "and",
    "the",
    "of",
    "in",
    "for",
}

# Suppress the expired-certificate warning (see module docstring).
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class KenyaPpipSource:
    """Pull live active tenders from the Kenya PPIP (tenders.go.ke) API."""

    name = "kenya_ppip"
    source_type = "kenya_ppip"

    def __init__(self, results_per_query: int = 20, timeout: int = 25) -> None:
        self.results_per_query = results_per_query
        self.timeout = timeout

    def _keyword(self, query: ServiceQuery) -> str:
        """Pick the most specific service word to filter the portal's title field."""
        tokens = [t for t in query.service.split() if len(t) >= 4]
        meaningful = [t for t in tokens if t.lower() not in _GENERIC_TERMS]
        pool = meaningful or tokens
        if not pool:
            return query.service.strip()
        return max(pool, key=len)

    def collect_leads(self, query: ServiceQuery, max_results: int = 20) -> list[Lead]:
        target = max(max_results, self.results_per_query)
        keyword = self._keyword(query)
        leads: list[Lead] = []
        page = 1
        last_page = 1
        max_pages = (target // PAGE_SIZE) + 2  # bound the crawl
        while page <= last_page and page <= max_pages and len(leads) < target:
            try:
                resp = requests.get(
                    API_URL,
                    params={"title": keyword, "page": str(page)},
                    timeout=self.timeout,
                    headers={"User-Agent": "Mozilla/5.0 (buyer-intent-scraper)"},
                    verify=False,
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Kenya PPIP API request failed (page %s): %s", page, exc)
                break
            last_page = int(payload.get("last_page") or 1)
            rows = payload.get("data") or []
            if not rows:
                break
            for row in rows:
                leads.append(self._tender_to_lead(row, query))
            page += 1
        return leads[:target]

    def _tender_to_lead(self, t: dict, query: ServiceQuery) -> Lead:
        created_by = t.get("created_by") or {}
        pe = t.get("pe") or created_by.get("pe") or {}
        name = str(pe.get("name") or "Kenya procuring entity").strip()
        title = str(t.get("title") or "").strip()
        description = str(t.get("description") or "").strip()

        contacts = " ".join(
            str(v)
            for v in (pe.get("email"), created_by.get("email"))
            if v
        )
        emails = extract_emails(contacts)
        phone_blob = " ".join(
            str(v)
            for v in (pe.get("telephone"), created_by.get("phone"))
            if v
        )
        phones = extract_phones(phone_blob, region="KE")

        city = str(pe.get("city") or "").strip()
        location = f"{city}, Kenya" if city else "Kenya"

        pe_type = (pe.get("type") or {}).get("description")
        entity_type = str(pe_type) if pe_type else classify_entity(name, title)

        category = ""
        pc = t.get("procurement_category")
        if isinstance(pc, dict):
            category = str(pc.get("description") or pc.get("name") or "")

        signal = f"{title}: {description}".strip(": ") if description else title

        return Lead(
            name=name,
            service=query.service,
            location=location,
            intent_signal=signal[:400],
            source_type=self.source_type,
            source_url=DETAIL_URL.format(id=t.get("id", "")),
            source_title=title[:200],
            entity_type=entity_type,
            intent_direction="requesting",  # every active tender is a buyer
            emails=emails,
            phones=phones,
            # Leave website blank: org_url is the procuring entity's domain, which
            # is shared across all of its tenders. Since dedupe_key() prefers
            # website, setting it would collapse every distinct tender from one
            # entity into a single lead (same convention as the World Bank source).
            website="",
            published_date=str(t.get("published_at") or "")[:10],
            deadline=str(t.get("close_at") or "")[:10],
            reference=str(t.get("tender_ref") or ""),
            category=category,
        )
