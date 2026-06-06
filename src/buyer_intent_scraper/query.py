"""Parse a plain-English buyer-intent query into structured fields."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Phrases that indicate the user is asking "who wants this service" — stripped
# from the front of a query before we try to read off the service + location.
_INTENT_PREFIXES = [
    r"who(?:'s| is| are| might be)?\s+(?:requesting|looking|searching|asking|in need of|seeking)\s+(?:for\s+)?",
    r"who(?:'s| is| are)?\s+(?:wants?|needs?)\s+",
    r"(?:find|get|show|list|search(?:\s+for)?|scrape|research)\s+(?:me\s+)?",
    r"(?:people|companies|businesses|organi[sz]ations|firms|leads)\s+(?:requesting|looking|seeking|that\s+(?:want|need))\s+(?:for\s+)?",
]

# Words that join a service to its location, split on the *last* occurrence so
# multi-word services like "office cleaning services" stay intact.
_LOCATION_SPLITTERS = [" in ", " around ", " near ", " within "]

# Buyer-intent keywords used to build dork queries. Order roughly by strength.
INTENT_KEYWORDS: list[str] = [
    "request for quotation",
    "request for proposal",
    "invitation to tender",
    "invitation to bid",
    "expression of interest",
    "tender",
    "RFQ",
    "RFP",
    "EOI",
    "looking for",
    "seeking",
    "need a",
    "we are hiring",
    "request for services",
]


@dataclass
class ServiceQuery:
    """Structured representation of a buyer-intent search."""

    service: str
    location: str = ""
    intent_keywords: list[str] = field(default_factory=lambda: list(INTENT_KEYWORDS))
    raw: str = ""

    @property
    def country(self) -> str:
        """Best-effort country guess from the location (last comma-part or whole)."""
        if not self.location:
            return ""
        parts = [p.strip() for p in re.split(r"[,/]", self.location) if p.strip()]
        return parts[-1] if parts else self.location

    def describe(self) -> str:
        loc = f" in {self.location}" if self.location else ""
        return f"{self.service}{loc}"


def _strip_intent_prefix(text: str) -> str:
    cleaned = text.strip()
    for pat in _INTENT_PREFIXES:
        cleaned = re.sub(rf"^{pat}", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


def _split_service_location(text: str) -> tuple[str, str]:
    lowered = text.lower()
    best_idx = -1
    best_tok = ""
    for tok in _LOCATION_SPLITTERS:
        idx = lowered.rfind(tok)
        if idx > best_idx:
            best_idx = idx
            best_tok = tok
    if best_idx == -1:
        return text.strip(), ""
    service = text[:best_idx].strip()
    location = text[best_idx + len(best_tok) :].strip()
    return service, location


def _normalize_location(location: str) -> str:
    """Normalize "Kenya Nairobi" / "nairobi kenya" style into "Nairobi, Kenya"."""
    if not location:
        return ""
    location = re.sub(r"\s+", " ", location).strip(" .,")
    if "," in location:
        parts = [p.strip().title() for p in location.split(",") if p.strip()]
        return ", ".join(parts)
    words = [w for w in location.split(" ") if w]
    if len(words) == 2:
        # Heuristic: assume "<City> <Country>"; keep order but comma-separate.
        return f"{words[0].title()}, {words[1].title()}"
    return location.title()


def parse_query(text: str, intent_keywords: list[str] | None = None) -> ServiceQuery:
    """Parse a plain-English query into a :class:`ServiceQuery`.

    Examples
    --------
    >>> parse_query("who are requesting for construction services in Kenya Nairobi").service
    'construction services'
    """
    raw = text.strip()
    stripped = _strip_intent_prefix(raw)
    service, location = _split_service_location(stripped)
    service = re.sub(r"\s+", " ", service).strip(" .,")
    location = _normalize_location(location)
    return ServiceQuery(
        service=service,
        location=location,
        intent_keywords=list(intent_keywords) if intent_keywords else list(INTENT_KEYWORDS),
        raw=raw,
    )
