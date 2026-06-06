"""Orchestrate the end-to-end pipeline: query -> sources -> extract -> leads."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import date, datetime, timezone

from buyer_intent_scraper.config import Config
from buyer_intent_scraper.extract import (
    ContactExtractor,
    classify_entity,
    classify_intent_direction,
    registered_domain,
)
from buyer_intent_scraper.models import Lead, SearchResult
from buyer_intent_scraper.query import ServiceQuery, parse_query
from buyer_intent_scraper.search import SearchBackend, get_search_backend
from buyer_intent_scraper.sources import (
    DirectorySource,
    GeminiAgentSource,
    GoogleDorkSource,
    LeadSource,
    Source,
    TenderPortalSource,
    WorldBankSource,
)

logger = logging.getLogger(__name__)

# Common country -> ccTLD, used to accept leads on a matching country domain
# even when the snippet text doesn't spell out the location.
_COUNTRY_TLDS = {
    "kenya": "ke",
    "uganda": "ug",
    "tanzania": "tz",
    "rwanda": "rw",
    "nigeria": "ng",
    "ghana": "gh",
    "south africa": "za",
    "ethiopia": "et",
}


def deadline_open(deadline: str, today: date | None = None) -> bool:
    """True if a submission deadline is today or in the future.

    Unknown/blank deadlines are treated as open (kept) since many legitimate
    leads simply don't publish a closing date in a parseable form.
    """
    if not deadline:
        return True
    today = today or datetime.now(timezone.utc).date()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(deadline[:10], fmt).date() >= today
        except ValueError:
            continue
    return True  # unparseable -> don't discard


def domain_blocked(url: str, blocklist: Iterable[str]) -> bool:
    """True if the URL's registered domain is in the blocklist."""
    domain = registered_domain(url).lower()
    if not domain:
        return False
    return any(domain == b.lower() or domain.endswith("." + b.lower()) for b in blocklist)


def location_relevant(lead: Lead, query: ServiceQuery) -> bool:
    """True if the lead plausibly belongs to the query's target location.

    A lead matches when its text mentions a location token (city/country) or
    when it sits on the target country's ccTLD (e.g. ``.ke`` for Kenya).
    """
    if not query.location:
        return True
    blob = f"{lead.source_title} {lead.intent_signal} {lead.name} {lead.location}".lower()
    tokens = [
        part.strip().lower()
        for part in re.split(r"[,/]", query.location)
        if len(part.strip()) >= 3
    ]
    if any(tok in blob for tok in tokens):
        return True
    tld = _COUNTRY_TLDS.get(query.country.lower(), "")
    if tld:
        domain = registered_domain(lead.source_url).lower()
        if domain.endswith("." + tld):
            return True
    return False


def build_sources(
    config: Config, backend: SearchBackend
) -> tuple[list[Source], list[LeadSource]]:
    """Return (search_sources, lead_sources) for the configured source names."""
    search_sources: list[Source] = []
    lead_sources: list[LeadSource] = []
    if "world_bank" in config.sources:
        lead_sources.append(WorldBankSource(results_per_query=config.max_results_per_source))
    if "agent" in config.sources:
        lead_sources.append(
            GeminiAgentSource(
                model=config.agent_model,
                max_steps=config.agent_max_steps,
                headless=config.agent_headless,
            )
        )
    if "google_dork" in config.sources:
        search_sources.append(
            GoogleDorkSource(
                backend=backend,
                results_per_dork=config.max_results_per_source,
                country_tld=config.country_tld,
            )
        )
    if "tender_portal" in config.sources:
        search_sources.append(
            TenderPortalSource(
                portals=config.tender_portals or None,
                backend=backend,
                results_per_dork=config.max_results_per_source,
            )
        )
    if "directory" in config.sources:
        search_sources.append(
            DirectorySource(
                directories=config.directories or None,
                backend=backend,
                results_per_dork=config.max_results_per_source,
            )
        )
    return search_sources, lead_sources


def score_lead(lead: Lead, query: ServiceQuery) -> float:
    """Heuristic 0-1 confidence score for a lead."""
    score = 0.2  # base for being surfaced at all
    if lead.emails:
        score += 0.3
    if lead.phones:
        score += 0.2
    if lead.website:
        score += 0.05

    blob = f"{lead.source_title} {lead.intent_signal}".lower()
    if query.service and query.service.lower() in blob:
        score += 0.1
    if any(kw.lower() in blob for kw in query.intent_keywords):
        score += 0.1
    if query.location and any(
        part.strip().lower() in blob
        for part in re.split(r"[,/]", query.location)
        if part.strip()
    ):
        score += 0.05
    if lead.source_type == "tender_portal":
        score += 0.05
    if lead.intent_direction == "requesting":
        score += 0.1
    elif lead.intent_direction == "offering":
        score -= 0.1
    return round(min(max(score, 0.0), 1.0), 3)


def dedupe_leads(leads: Iterable[Lead]) -> list[Lead]:
    best: dict[str, Lead] = {}
    for lead in leads:
        key = lead.dedupe_key()
        existing = best.get(key)
        if existing is None or lead.confidence > existing.confidence:
            best[key] = lead
    return list(best.values())


def _result_to_lead(
    result: SearchResult,
    query: ServiceQuery,
    extractor: ContactExtractor,
) -> Lead:
    contacts = extractor.extract(result.url, fallback_text=result.snippet)
    name = contacts.name or result.title or result.url
    # For dork hits the page is plausibly the entity's own site, so its domain is
    # a useful "website". For portal/directory hits the domain is the portal, not
    # the lead, so we leave website blank to avoid bad dedupe collisions.
    website = contacts.website if result.source_type == "google_dork" else ""
    direction_blob = f"{result.title} {result.snippet} {contacts.page_text}"
    lead = Lead(
        name=name,
        service=query.service,
        location=query.location,
        intent_signal=(result.snippet or result.title)[:400],
        source_type=result.source_type,
        source_url=result.url,
        source_title=result.title,
        entity_type=classify_entity(name, contacts.page_text),
        intent_direction=classify_intent_direction(direction_blob, result.source_type),
        emails=contacts.emails,
        phones=contacts.phones,
        website=website,
    )
    lead.confidence = score_lead(lead, query)
    return lead


def run_query(
    query_text: str,
    config: Config | None = None,
    backend: SearchBackend | None = None,
) -> list[Lead]:
    """Run the full pipeline for a single plain-English query."""
    config = config or Config()
    backend = backend or get_search_backend()
    query = parse_query(query_text)
    logger.info("Parsed query: service=%r location=%r", query.service, query.location)

    search_sources, lead_sources = build_sources(config, backend)
    results: list[SearchResult] = []
    direct_leads: list[Lead] = []
    for source in search_sources:
        try:
            found = source.collect(query, max_results=config.max_results_per_source)
            logger.info("[%s] %d results", source.name, len(found))
            results.extend(found)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source %s failed: %s", source.name, exc)
    for lead_source in lead_sources:
        try:
            found_leads = lead_source.collect_leads(
                query, max_results=config.max_results_per_source
            )
            logger.info("[%s] %d leads", lead_source.name, len(found_leads))
            direct_leads.extend(found_leads)
        except Exception as exc:  # noqa: BLE001
            logger.warning("source %s failed: %s", lead_source.name, exc)

    if config.blocklist_domains:
        before = len(results)
        results = [r for r in results if not domain_blocked(r.url, config.blocklist_domains)]
        if before != len(results):
            logger.info("blocklist removed %d aggregator result(s)", before - len(results))

    extractor = ContactExtractor.for_country(
        query.country, respect_robots=config.respect_robots
    )
    leads = [_result_to_lead(r, query, extractor) for r in results]
    for lead in direct_leads:
        lead.confidence = score_lead(lead, query)
    leads.extend(direct_leads)
    leads = dedupe_leads(leads)

    if config.open_only:
        leads = [lead for lead in leads if deadline_open(lead.deadline)]
    if config.require_location_match:
        leads = [lead for lead in leads if location_relevant(lead, query)]
    if config.only_requesting:
        leads = [lead for lead in leads if lead.intent_direction == "requesting"]
    if config.require_contact:
        leads = [lead for lead in leads if lead.has_contact()]
    if config.min_confidence > 0:
        leads = [lead for lead in leads if lead.confidence >= config.min_confidence]

    leads.sort(key=lambda lead: lead.confidence, reverse=True)
    return leads[: config.max_leads_per_query]
