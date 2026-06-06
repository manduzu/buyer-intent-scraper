from datetime import date

from buyer_intent_scraper.config import Config
from buyer_intent_scraper.extract import ContactExtractor
from buyer_intent_scraper.models import Lead, SearchResult
from buyer_intent_scraper.pipeline import (
    deadline_open,
    dedupe_leads,
    domain_blocked,
    location_relevant,
    run_query,
    score_lead,
)
from buyer_intent_scraper.query import parse_query
from buyer_intent_scraper.sources.world_bank import WorldBankSource


class FakeBackend:
    name = "fake"

    def __init__(self, results):
        self._results = results
        self.queries = []

    def search(self, query, max_results=10):
        self.queries.append(query)
        return self._results[:max_results]


PAGE = """
<html><head><title>Tumaini Contractors Ltd</title></head><body>
We are looking for construction services. Tender notice.
<a href="mailto:tenders@tumaini.co.ke">email</a> +254712000111
</body></html>
"""


def test_run_query_builds_scored_leads(monkeypatch):
    results = [
        SearchResult(
            title="Tumaini Contractors Ltd",
            url="https://tumaini.co.ke/tender",
            snippet="We are looking for construction services in Nairobi",
            source_type="search",
            source_name="fake",
        )
    ]
    backend = FakeBackend(results)
    monkeypatch.setattr(ContactExtractor, "fetch", lambda self, url: PAGE)

    config = Config(sources=["google_dork"], max_results_per_source=5)
    leads = run_query("construction services in Nairobi, Kenya", config=config, backend=backend)

    assert leads, "expected at least one lead"
    lead = leads[0]
    assert "tenders@tumaini.co.ke" in lead.emails
    assert any(p.startswith("+254") for p in lead.phones)
    assert lead.confidence > 0.5
    assert backend.queries, "backend should have been queried"


def test_require_contact_filters(monkeypatch):
    results = [
        SearchResult("No Contact Co", "https://nocontact.example/x", "looking for X", "search")
    ]
    backend = FakeBackend(results)
    monkeypatch.setattr(ContactExtractor, "fetch", lambda self, url: "<html></html>")

    config = Config(sources=["google_dork"], require_contact=True)
    leads = run_query("cleaning services in Nairobi", config=config, backend=backend)
    assert leads == []


def test_domain_blocked_and_location_relevant():
    q = parse_query("construction services in Nairobi, Kenya")
    assert domain_blocked("https://www.biddetail.com/kenya/rfq", ["biddetail.com"])
    assert not domain_blocked("https://tenders.go.ke/notice", ["biddetail.com"])

    kenyan = Lead(
        name="NCIA", service="construction services", location="Nairobi, Kenya",
        intent_signal="tender notice", source_type="tender_portal",
        source_url="https://tenders.go.ke/x",
    )
    foreign = Lead(
        name="Namibia Tenders", service="construction services", location="Windhoek, Namibia",
        intent_signal="Namibia tender for road works", source_type="tender_portal",
        source_url="https://unifiedtenders.com/namibia",
    )
    assert location_relevant(kenyan, q)  # matches via .ke domain
    assert not location_relevant(foreign, q)  # off-target, dropped


def test_score_and_dedupe():
    q = parse_query("construction services in Nairobi, Kenya")
    a = Lead(
        name="A", service="construction services", location="Nairobi, Kenya",
        intent_signal="tender for construction services", source_type="tender_portal",
        source_url="https://x.co.ke/a", website="x.co.ke", emails=["a@x.co.ke"],
    )
    b = Lead(
        name="A dup", service="construction services", location="Nairobi, Kenya",
        intent_signal="construction services", source_type="directory",
        source_url="https://x.co.ke/b", website="x.co.ke",
    )
    a.confidence = score_lead(a, q)
    b.confidence = score_lead(b, q)
    assert a.confidence > b.confidence
    deduped = dedupe_leads([b, a])
    assert len(deduped) == 1
    assert deduped[0].name == "A"  # higher-confidence lead wins


def test_deadline_open():
    today = date(2026, 6, 6)
    assert deadline_open("2026-07-02", today=today)  # future -> open
    assert deadline_open("2026-06-06", today=today)  # today -> open
    assert not deadline_open("2026-01-01", today=today)  # past -> closed
    assert deadline_open("", today=today)  # unknown -> kept
    assert deadline_open("not-a-date", today=today)  # unparseable -> kept


def test_world_bank_notice_to_lead():
    src = WorldBankSource()
    q = parse_query("construction works in Kenya")
    notice = {
        "id": "OP00449225",
        "notice_type": "Invitation for Bids",
        "noticedate": "05-Jun-2026",
        "submission_deadline_date": "2026-07-02T00:00:00Z",
        "project_ctry_name": "Kenya",
        "project_name": "Water Supply Expansion",
        "bid_reference_no": "KE-WSP-123",
        "bid_description": "Construction works for the expansion of a water plant",
        "procurement_method_name": "Open Competitive Bidding",
        "contact_organization": "Ministry of Water",
        "contact_email": "procurement@water.go.ke",
        "contact_phone_no": "+254712345678",
    }
    lead = src._notice_to_lead(notice, q)
    assert lead.name == "Ministry of Water"
    assert lead.intent_direction == "requesting"
    assert lead.deadline == "2026-07-02"
    assert lead.reference == "KE-WSP-123"
    assert "procurement@water.go.ke" in lead.emails
    assert lead.source_url.endswith("OP00449225")

    award = dict(notice, notice_type="Contract Award", submission_deadline_date="")
    assert src._notice_to_lead(award, q).intent_direction != "requesting"
