"""Buyer-intent lead-generation scraper.

Given a plain-English query like "who is requesting construction services in
Nairobi, Kenya", this package researches publicly available web pages (via
search-engine dorking, public tender/procurement portals and B2B directories)
to find entities signalling buyer intent, extracts public contact details and
exports the results to CSV.
"""

from buyer_intent_scraper.models import Lead, SearchResult
from buyer_intent_scraper.query import ServiceQuery, parse_query

__all__ = ["Lead", "SearchResult", "ServiceQuery", "parse_query"]
__version__ = "0.1.0"
