"""World Bank procurement-notices source.

The World Bank publishes structured procurement notices (Invitations for Bids,
Requests for Expressions of Interest, etc.) via a public JSON API. Each notice
already carries the procuring entity's contact details and a submission
deadline, so this source yields fully-formed :class:`Lead` objects directly
without a separate page fetch.
"""

from __future__ import annotations

import logging

import requests

from buyer_intent_scraper.extract import classify_entity, extract_emails, extract_phones
from buyer_intent_scraper.models import Lead
from buyer_intent_scraper.query import ServiceQuery

logger = logging.getLogger(__name__)

API_URL = "https://search.worldbank.org/api/v2/procnotices"
NOTICE_URL = "https://projects.worldbank.org/en/projects-operations/procurement-detail/{id}"

# Notice types that represent a buyer requesting work (demand-side).
_REQUESTING_TYPES = {
    "invitation for bids",
    "invitation to bid",
    "request for expression of interest",
    "request for expressions of interest",
    "request for proposals",
    "request for quotations",
    "request for bids",
    "general procurement notice",
    "specific procurement notice",
}


class WorldBankSource:
    """Pull live procurement notices from the World Bank API."""

    name = "world_bank"
    source_type = "world_bank"

    def __init__(self, results_per_query: int = 20, timeout: int = 25) -> None:
        self.results_per_query = results_per_query
        self.timeout = timeout

    def _query_term(self, query: ServiceQuery) -> str:
        parts = [query.service]
        if query.country:
            parts.append(query.country)
        return " ".join(p for p in parts if p).strip()

    def collect_leads(self, query: ServiceQuery, max_results: int = 20) -> list[Lead]:
        params = {
            "format": "json",
            "rows": str(max(max_results, self.results_per_query)),
            "srt": "submission_date",
            "order": "desc",
            "qterm": self._query_term(query),
        }
        try:
            resp = requests.get(
                API_URL,
                params=params,
                timeout=self.timeout,
                headers={"User-Agent": "Mozilla/5.0 (buyer-intent-scraper)"},
            )
            resp.raise_for_status()
            notices = resp.json().get("procnotices", [])
        except (requests.RequestException, ValueError) as exc:
            logger.warning("World Bank API request failed: %s", exc)
            return []

        leads: list[Lead] = []
        for n in notices:
            leads.append(self._notice_to_lead(n, query))
        return leads

    def _notice_to_lead(self, n: dict, query: ServiceQuery) -> Lead:
        notice_type = (n.get("notice_type") or "").strip()
        org = n.get("contact_organization") or n.get("project_name") or "World Bank notice"
        description = n.get("bid_description") or n.get("project_name") or ""
        country = n.get("project_ctry_name") or n.get("contact_ctry_name") or query.location

        emails: list[str] = []
        if n.get("contact_email"):
            emails = extract_emails(str(n["contact_email"])) or [str(n["contact_email"]).strip()]
        phones: list[str] = []
        if n.get("contact_phone_no"):
            phones = extract_phones(str(n["contact_phone_no"]), region="") or [
                str(n["contact_phone_no"]).strip()
            ]

        direction = "requesting" if notice_type.lower() in _REQUESTING_TYPES else "unknown"
        deadline = (n.get("submission_deadline_date") or "")[:10]
        notice_id = n.get("id") or ""

        return Lead(
            name=str(org).strip(),
            service=query.service,
            location=str(country).strip(),
            intent_signal=f"{notice_type}: {description}"[:400],
            source_type=self.source_type,
            source_url=NOTICE_URL.format(id=notice_id) if notice_id else "",
            source_title=str(n.get("project_name") or notice_type)[:200],
            entity_type=classify_entity(str(org), description),
            intent_direction=direction,
            emails=emails,
            phones=phones,
            website="",
            published_date=(n.get("noticedate") or ""),
            deadline=deadline,
            reference=str(n.get("bid_reference_no") or ""),
            category=str(n.get("procurement_method_name") or n.get("procurement_group") or ""),
        )
