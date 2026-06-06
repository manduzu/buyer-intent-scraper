"""Core data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class SearchResult:
    """A single result returned by a search backend or source crawler."""

    title: str
    url: str
    snippet: str
    source_type: str  # e.g. "google_dork", "tender_portal", "directory"
    source_name: str = ""  # e.g. the portal/directory domain it came from


@dataclass
class Lead:
    """A buyer-intent lead extracted from a public web page."""

    name: str
    service: str
    location: str
    intent_signal: str
    source_type: str
    source_url: str
    source_title: str = ""
    entity_type: str = "unknown"  # company | individual | organization | government | unknown
    intent_direction: str = "unknown"  # requesting | offering | unknown
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    website: str = ""
    published_date: str = ""
    deadline: str = ""  # submission/closing date (YYYY-MM-DD) when known
    reference: str = ""  # tender / bid reference number
    category: str = ""  # procurement category or method
    confidence: float = 0.0
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def dedupe_key(self) -> str:
        """Key used to deduplicate leads across sources.

        Website (only set for the entity's own domain) identifies the entity
        best; otherwise fall back to the first email, then the source URL.
        """
        if self.website:
            return self.website.lower()
        if self.emails:
            return sorted(e.lower() for e in self.emails)[0]
        return self.source_url.split("#")[0].rstrip("/").lower()

    def has_contact(self) -> bool:
        """A usable contact means an actual email or phone to reach out on."""
        return bool(self.emails or self.phones)
