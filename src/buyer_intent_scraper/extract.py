"""Fetch public pages and extract contact details from them.

Only publicly available pages are fetched. ``robots.txt`` is respected by
default and a polite delay + descriptive User-Agent are used. No pages behind
logins or paywalls are accessed.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import phonenumbers
import requests
import tldextract
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

USER_AGENT = (
    "buyer-intent-scraper/0.1 (+https://github.com/manduzu/buyer-intent-scraper) "
    "polite-research-bot"
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)
# Junk emails we never want to surface as leads.
_EMAIL_BLOCKLIST = re.compile(
    r"(?:\.png|\.jpg|\.jpeg|\.gif|\.webp|\.svg|sentry|example\.com|wixpress|"
    r"@2x|domain\.com|email@|your-email|name@)",
    re.IGNORECASE,
)

# Default region for bare national phone numbers (Kenya). Overridden per-query.
DEFAULT_REGION = "KE"

_COMPANY_HINTS = re.compile(
    r"\b(ltd|limited|llc|inc|plc|company|co\.|enterprises?|holdings?|group|"
    r"services?|solutions?|contractors?|builders?|construction)\b",
    re.IGNORECASE,
)
_GOV_HINTS = re.compile(
    r"\b(ministry|county|government|authority|county\s+government|board|"
    r"commission|parastatal|agency|public)\b",
    re.IGNORECASE,
)
_ORG_HINTS = re.compile(
    r"\b(ngo|foundation|trust|association|society|sacco|cooperative|church|"
    r"university|college|school|hospital)\b",
    re.IGNORECASE,
)


@dataclass
class Contacts:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    website: str = ""
    name: str = ""
    page_text: str = ""
    fetched: bool = False


def registered_domain(url: str) -> str:
    ext = tldextract.extract(url)
    if not ext.domain:
        return ""
    return ".".join(p for p in [ext.domain, ext.suffix] if p)


def classify_entity(name: str, text: str = "") -> str:
    blob = f"{name} {text[:500]}"
    if _GOV_HINTS.search(blob):
        return "government"
    if _ORG_HINTS.search(blob):
        return "organization"
    if _COMPANY_HINTS.search(blob):
        return "company"
    return "unknown"


# Demand-side language: the entity is *requesting* / buying a service.
_REQUESTING_RE = re.compile(
    r"\b("
    r"request for (quotation|proposal|proposals|tender|tenders|bid|bids|information|"
    r"expression of interest)|"
    r"rfq|rfp|rfi|eoi|"
    r"invitation (to|for) (tender|tenders|bid|bids)|"
    r"invitation for bids|"
    r"tender (notice|no\.?|ref\.?|number|reference|document)|"
    r"prequalification|pre-qualification|"
    r"call for (proposals|bids|tenders|applications|quotations)|"
    r"expression[s]? of interest|"
    r"looking for (a |an |our )?(contractor|supplier|vendor|provider|company|firm|consultant)|"
    r"seeking (a |an )?(contractor|supplier|vendor|provider|quotes?|quotation|proposals?)|"
    r"we (are looking for|require|need|are seeking|are inviting)|"
    r"submit (your )?(a )?(bid|bids|quotation|quotations|proposal|proposals|tender)|"
    r"bidders|bidding documents|procuring entity|"
    r"(wanted|needed)\b|"
    r"closing date|submission deadline|due date"
    r")\b",
    re.IGNORECASE,
)

# Supply-side language: the entity is *offering* / selling a service.
_OFFERING_RE = re.compile(
    r"\b("
    r"we (offer|provide|speciali[sz]e|deliver|supply)|"
    r"our (services|products|solutions|portfolio|clients|team)|"
    r"services (include|offered)|"
    r"we are (a |an |the )?(leading|premier|trusted|top|best|number one|reliable)|"
    r"leading (provider|supplier|contractor|company|manufacturer)|"
    r"(get|request|ask for) (a )?(free )?(quote|estimate)|"
    r"contact us (for|today)|"
    r"for all your .{0,30} needs|"
    r"years of experience|established in|since \d{4}|"
    r"for sale|buy now|shop now|add to cart|our pricing|view our"
    r")\b",
    re.IGNORECASE,
)


def classify_intent_direction(text: str, source_type: str = "") -> str:
    """Classify whether the page reflects *requesting* vs *offering* a service.

    Returns ``"requesting"``, ``"offering"`` or ``"unknown"``. Text signals
    dominate; the source type only nudges the decision (tender portals lean
    requesting, directories lean offering).
    """
    blob = text[:4000]
    req = len(_REQUESTING_RE.findall(blob))
    off = len(_OFFERING_RE.findall(blob))
    if source_type == "tender_portal":
        req += 2
    elif source_type == "directory":
        off += 2
    if req == 0 and off == 0:
        return "unknown"
    if req > off:
        return "requesting"
    if off > req:
        return "offering"
    return "unknown"


def extract_emails(text: str) -> list[str]:
    found: list[str] = []
    for m in _EMAIL_RE.findall(text or ""):
        email = m.strip().strip(".")
        if _EMAIL_BLOCKLIST.search(email):
            continue
        if email.lower() not in (e.lower() for e in found):
            found.append(email)
    return found


def extract_phones(text: str, region: str = DEFAULT_REGION) -> list[str]:
    found: list[str] = []
    try:
        for match in phonenumbers.PhoneNumberMatcher(text or "", region):
            formatted = phonenumbers.format_number(
                match.number, phonenumbers.PhoneNumberFormat.E164
            )
            if formatted not in found:
                found.append(formatted)
    except Exception as exc:  # noqa: BLE001
        logger.debug("phone parsing failed: %s", exc)
    return found


def _region_from_country(country: str) -> str:
    if not country:
        return DEFAULT_REGION
    mapping = {
        "kenya": "KE",
        "uganda": "UG",
        "tanzania": "TZ",
        "nigeria": "NG",
        "south africa": "ZA",
        "ghana": "GH",
        "rwanda": "RW",
        "ethiopia": "ET",
        "united states": "US",
        "usa": "US",
        "united kingdom": "GB",
        "uk": "GB",
    }
    return mapping.get(country.strip().lower(), DEFAULT_REGION)


class ContactExtractor:
    def __init__(
        self,
        respect_robots: bool = True,
        timeout: int = 20,
        pause: float = 0.5,
        region: str = DEFAULT_REGION,
    ) -> None:
        self.respect_robots = respect_robots
        self.timeout = timeout
        self.pause = pause
        self.region = region
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._robots_cache: dict[str, RobotFileParser | None] = {}

    @classmethod
    def for_country(cls, country: str, **kwargs) -> ContactExtractor:
        return cls(region=_region_from_country(country), **kwargs)

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(base)
        if rp is None and base not in self._robots_cache:
            rp = RobotFileParser()
            rp.set_url(f"{base}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001 - treat unreadable robots as allow
                rp = None
            self._robots_cache[base] = rp
        if rp is None:
            return True
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:  # noqa: BLE001
            return True

    def fetch(self, url: str) -> str:
        if not self._allowed(url):
            logger.info("robots.txt disallows %s; skipping", url)
            return ""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype and "text" not in ctype:
                return ""
            return resp.text
        except Exception as exc:  # noqa: BLE001
            logger.info("fetch failed for %s: %s", url, exc)
            return ""
        finally:
            time.sleep(self.pause)

    def extract(self, url: str, fallback_text: str = "") -> Contacts:
        """Fetch ``url`` and extract contacts; fall back to ``fallback_text``."""
        html = self.fetch(url)
        contacts = Contacts(website=registered_domain(url), fetched=bool(html))

        text_blob = fallback_text
        if html:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()

            # mailto / tel links are the most reliable contact sources.
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                if not isinstance(href, str):
                    continue
                if href.lower().startswith("mailto:"):
                    text_blob += " " + href.split(":", 1)[1].split("?")[0]
                elif href.lower().startswith("tel:"):
                    text_blob += " " + href.split(":", 1)[1]

            title = soup.find("title")
            og = soup.find("meta", attrs={"property": "og:site_name"})
            og_content = og.get("content") if isinstance(og, Tag) else None
            if isinstance(og_content, str) and og_content.strip():
                contacts.name = og_content.strip()
            elif isinstance(title, Tag) and title.get_text(strip=True):
                contacts.name = title.get_text(strip=True)

            text_blob += " " + soup.get_text(" ", strip=True)

        contacts.page_text = text_blob
        contacts.emails = extract_emails(text_blob)
        contacts.phones = extract_phones(text_blob, region=self.region)
        if not contacts.name:
            contacts.name = contacts.website or url
        return contacts
