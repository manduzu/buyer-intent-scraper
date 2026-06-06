from buyer_intent_scraper.config import Config
from buyer_intent_scraper.extract import ContactExtractor
from buyer_intent_scraper.models import SearchResult
from buyer_intent_scraper.pipeline import dedupe_leads, run_query, score_lead
from buyer_intent_scraper.query import parse_query


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


def test_score_and_dedupe():
    q = parse_query("construction services in Nairobi, Kenya")
    from buyer_intent_scraper.models import Lead

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
