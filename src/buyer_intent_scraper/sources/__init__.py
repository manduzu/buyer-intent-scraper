"""Source crawlers that turn a structured query into candidate web pages."""

from buyer_intent_scraper.sources.agent import GeminiAgentSource
from buyer_intent_scraper.sources.base import LeadSource, Source
from buyer_intent_scraper.sources.directories import DirectorySource
from buyer_intent_scraper.sources.google_dork import GoogleDorkSource
from buyer_intent_scraper.sources.kenya_ppip import KenyaPpipSource
from buyer_intent_scraper.sources.tender_portals import TenderPortalSource
from buyer_intent_scraper.sources.world_bank import WorldBankSource

__all__ = [
    "Source",
    "LeadSource",
    "GoogleDorkSource",
    "TenderPortalSource",
    "DirectorySource",
    "WorldBankSource",
    "KenyaPpipSource",
    "GeminiAgentSource",
]
