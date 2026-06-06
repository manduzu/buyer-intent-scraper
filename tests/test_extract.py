from buyer_intent_scraper.extract import (
    ContactExtractor,
    classify_entity,
    classify_intent_direction,
    extract_emails,
    extract_phones,
    registered_domain,
)

SAMPLE_HTML = """
<html><head><title>Acme Builders Ltd</title>
<meta property="og:site_name" content="Acme Builders Ltd"></head>
<body>
<p>We are looking for a construction contractor in Nairobi.</p>
<a href="mailto:info@acmebuilders.co.ke">Email us</a>
<a href="tel:+254712345678">Call us</a>
Contact: procurement@acmebuilders.co.ke or 0723 456 789
<img src="logo.png">
</body></html>
"""


def test_extract_emails_filters_junk():
    emails = extract_emails(SAMPLE_HTML + " bad@logo.png you@example.com")
    assert "info@acmebuilders.co.ke" in emails
    assert "procurement@acmebuilders.co.ke" in emails
    assert all("example.com" not in e for e in emails)
    assert all(not e.endswith(".png") for e in emails)


def test_extract_phones_kenya_region():
    phones = extract_phones("Call 0712 345 678 or +254723456789", region="KE")
    assert "+254712345678" in phones
    assert "+254723456789" in phones


def test_registered_domain():
    assert registered_domain("https://www.acmebuilders.co.ke/contact") == "acmebuilders.co.ke"


def test_classify_entity():
    assert classify_entity("Acme Builders Ltd") == "company"
    assert classify_entity("Nairobi County Government") == "government"
    assert classify_entity("Hope Foundation Trust") == "organization"
    assert classify_entity("John Doe") == "unknown"


def test_classify_intent_direction():
    # Demand-side language -> requesting.
    assert (
        classify_intent_direction("Invitation to tender for road works. Closing date 5 May.")
        == "requesting"
    )
    assert (
        classify_intent_direction("We are looking for a supplier to provide cement.")
        == "requesting"
    )
    # Supply-side language -> offering.
    assert (
        classify_intent_direction("We are a leading provider. We offer the best services.")
        == "offering"
    )
    # Source priors nudge ambiguous text.
    assert classify_intent_direction("Project listing", source_type="tender_portal") == "requesting"
    assert classify_intent_direction("Business listing", source_type="directory") == "offering"
    assert classify_intent_direction("nothing relevant here") == "unknown"


def test_extract_from_html_offline(monkeypatch):
    # Monkeypatch fetch so the HTML parsing path runs deterministically offline.
    extractor = ContactExtractor(respect_robots=False, region="KE")
    monkeypatch.setattr(extractor, "fetch", lambda url: SAMPLE_HTML)
    contacts = extractor.extract("https://acmebuilders.co.ke")
    assert "info@acmebuilders.co.ke" in contacts.emails
    assert any(p.startswith("+254") for p in contacts.phones)
    assert contacts.website == "acmebuilders.co.ke"
    assert contacts.name == "Acme Builders Ltd"
    assert contacts.fetched is True
