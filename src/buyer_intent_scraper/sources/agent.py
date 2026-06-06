"""Gemini ``browser_use`` agent source (Engine 3).

This source drives a real browser with an LLM (Google Gemini, free tier) to
*navigate* live pages and extract structured buyer-intent leads, rather than
reading search-result snippets. It is optional: ``browser_use`` is a heavy
dependency installed via the ``agent`` extra, and the source degrades gracefully
(returns no leads with a logged warning) when it is missing or no API key is set.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from buyer_intent_scraper.extract import classify_entity, extract_emails, extract_phones
from buyer_intent_scraper.models import Lead
from buyer_intent_scraper.query import ServiceQuery

logger = logging.getLogger(__name__)

_TASK_TEMPLATE = """\
You are a procurement researcher. Find organizations, companies, government \
bodies, counties, co-operative societies (SACCOs) and institutions that are \
REQUESTING (buying / tendering for) "{service}" in "{location}".

Only include DEMAND-SIDE entities that have an OPEN (not yet closed) request: \
tenders, RFQs, RFPs, "invitation to bid", "expression of interest", or public \
"we are looking for / we require" notices. Do NOT include providers, sellers or \
companies advertising that they OFFER the service.

Rules:
- Target entities based in or whose notice applies to {location}.
- Ignore tender aggregator/reseller sites (e.g. biddetail, tenderdetail).
- Prefer official portals and the buyer's own website; open the page and read the \
real contact details (email, phone, address).
- Find up to {max_results} distinct leads. For each, capture the exact source URL \
of the intent evidence.
Return ONLY the structured data in the requested schema."""


class GeminiAgentSource:
    """Pull leads via a ``browser_use`` agent powered by Google Gemini."""

    name = "agent"
    source_type = "agent"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash-lite",
        max_steps: int = 10,
        headless: bool = True,
        chrome_path: str | None = None,
        cdp_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model
        self.max_steps = max_steps
        self.headless = headless
        self.chrome_path = chrome_path or os.environ.get("CHROME_PATH", "")
        self.cdp_url = cdp_url or os.environ.get("CHROME_CDP_URL", "")

    def collect_leads(self, query: ServiceQuery, max_results: int = 10) -> list[Lead]:
        if not self.api_key:
            logger.warning("agent source skipped: no GEMINI_API_KEY set")
            return []
        try:
            records = asyncio.run(self._run_agent(query, max_results))
        except RuntimeError as exc:
            # e.g. called from within an existing event loop
            logger.warning("agent source could not start event loop: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("agent source failed: %s", exc)
            return []
        return [self._record_to_lead(r, query) for r in records]

    def _seed_url(self, query: ServiceQuery) -> str:
        """A Google results page targeting open tenders for the query.

        Landing here (instead of letting the agent blind-search) cuts steps and
        keeps it on high-signal pages.
        """
        from urllib.parse import quote_plus

        loc = query.location or query.country or ""
        terms = f'{query.service} {loc} tender OR "request for quotation" OR "expression of interest"'
        return f"https://www.google.com/search?q={quote_plus(terms)}"

    async def _run_agent(self, query: ServiceQuery, max_results: int) -> list[dict[str, Any]]:
        try:
            from browser_use import Agent, Browser, ChatGoogle
        except ImportError:
            logger.warning(
                "agent source requires browser_use; install with: pip install '.[agent]'"
            )
            return []

        from pydantic import BaseModel

        class LeadModel(BaseModel):
            business_name: str
            entity_type: str = "unknown"
            website: str = ""
            contact_email: str = ""
            phone_number: str = ""
            intent_evidence_url: str = ""
            intent_summary: str = ""
            physical_address: str = ""

        class LeadRecords(BaseModel):
            leads: list[LeadModel]

        task = _TASK_TEMPLATE.format(
            service=query.service,
            location=query.location or query.country or "the target location",
            max_results=max_results,
        )
        # Seed the agent straight onto a results page so it doesn't waste
        # steps (and tokens) blind-searching, then navigating from scratch.
        seed_url = self._seed_url(query)
        initial_actions = [{"navigate": {"url": seed_url, "new_tab": False}}]
        llm = ChatGoogle(model=self.model, api_key=self.api_key)
        if self.cdp_url:
            browser_kwargs: dict[str, Any] = {"cdp_url": self.cdp_url}
        else:
            browser_kwargs = {"headless": self.headless, "args": ["--no-sandbox"]}
            if self.chrome_path:
                browser_kwargs["executable_path"] = self.chrome_path
        browser = Browser(**browser_kwargs)
        agent: Any = Agent(
            task=task,
            llm=llm,
            browser=browser,
            output_model_schema=LeadRecords,
            initial_actions=initial_actions,
            # --- token-frugal settings ---
            use_vision=False,  # no screenshots sent to the model
            flash_mode=True,  # skip the verbose reasoning/eval blocks
            use_thinking=False,  # drop chain-of-thought tokens
            max_history_items=6,  # only keep recent steps in the prompt
            max_actions_per_step=4,  # batch actions -> fewer LLM round-trips
            max_failures=3,  # stop after a few errors instead of looping
        )
        try:
            history = await agent.run(max_steps=self.max_steps)
        finally:
            if not self.cdp_url:  # don't tear down a shared/attached browser
                try:
                    await browser.kill()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("browser shutdown error: %s", exc)

        final = history.final_result()
        if not final:
            return []
        try:
            data = json.loads(final)
        except (ValueError, TypeError):
            logger.warning("agent returned non-JSON result")
            return []
        leads = data.get("leads", []) if isinstance(data, dict) else []
        return [r for r in leads if isinstance(r, dict)]

    def _record_to_lead(self, r: dict[str, Any], query: ServiceQuery) -> Lead:
        name = str(r.get("business_name") or "Unknown entity").strip()
        email_raw = str(r.get("contact_email") or "").strip()
        phone_raw = str(r.get("phone_number") or "").strip()
        emails = extract_emails(email_raw) or ([email_raw] if "@" in email_raw else [])
        phones = extract_phones(phone_raw, region="") or ([phone_raw] if phone_raw else [])
        summary = str(r.get("intent_summary") or "").strip()
        return Lead(
            name=name,
            service=query.service,
            location=str(r.get("physical_address") or query.location).strip(),
            intent_signal=(summary or f"Requesting {query.service}")[:400],
            source_type=self.source_type,
            source_url=str(r.get("intent_evidence_url") or r.get("website") or "").strip(),
            source_title=name,
            entity_type=str(r.get("entity_type") or classify_entity(name, summary)).strip()
            or "unknown",
            intent_direction="requesting",
            emails=emails,
            phones=phones,
            website=str(r.get("website") or "").strip(),
        )
