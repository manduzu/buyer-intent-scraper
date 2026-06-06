from buyer_intent_scraper.query import parse_query


def test_parses_who_is_requesting_phrasing():
    q = parse_query("who are requesting for construction services in Kenya Nairobi")
    assert q.service == "construction services"
    assert q.location == "Kenya, Nairobi"


def test_parses_simple_service_in_location():
    q = parse_query("construction services in Nairobi, Kenya")
    assert q.service == "construction services"
    assert q.location == "Nairobi, Kenya"
    assert q.country == "Kenya"


def test_strips_find_me_prefix():
    q = parse_query("find me companies looking for borehole drilling in Kiambu")
    assert "borehole drilling" in q.service
    assert q.location == "Kiambu"


def test_no_location():
    q = parse_query("solar installation services")
    assert q.service == "solar installation services"
    assert q.location == ""
    assert q.country == ""


def test_intent_keywords_present():
    q = parse_query("cleaning services in Mombasa")
    assert any("tender" == kw for kw in q.intent_keywords)
    assert q.describe() == "cleaning services in Mombasa"
