"""YAML configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class EmailConfig:
    enabled: bool = False
    smtp_host: str = "${SMTP_HOST}"
    smtp_port: int = 587
    smtp_user: str = "${SMTP_USER}"
    smtp_password: str = "${SMTP_PASSWORD}"
    sender: str = "${EMAIL_FROM}"
    recipients: list[str] = field(default_factory=list)
    subject: str = "Buyer-intent leads"


@dataclass
class Config:
    queries: list[str] = field(default_factory=list)
    sources: list[str] = field(
        default_factory=lambda: [
            "world_bank",
            "kenya_ppip",
            "google_dork",
            "tender_portal",
            "directory",
        ]
    )
    max_results_per_source: int = 10
    max_leads_per_query: int = 50
    min_confidence: float = 0.0
    require_contact: bool = False
    only_requesting: bool = True  # keep only demand-side (requesting) leads
    open_only: bool = True  # drop notices whose submission deadline has passed
    require_location_match: bool = True  # drop leads not tied to the target location
    blocklist_domains: list[str] = field(
        default_factory=lambda: ["biddetail.com", "tenderdetail.com"]
    )
    respect_robots: bool = True
    country_tld: str = ""
    agent_model: str = "gemini-2.5-flash-lite"  # Gemini model for the browser_use agent
    agent_max_steps: int = 10  # cap on agent navigation steps per query
    agent_headless: bool = True  # run the agent browser headless
    tender_portals: list[str] = field(default_factory=list)
    directories: list[str] = field(default_factory=list)
    output_dir: str = "out"
    output_format: str = "xlsx"  # xlsx | csv | both
    email: EmailConfig = field(default_factory=EmailConfig)

    @classmethod
    def load(cls, path: str | Path) -> Config:
        data = yaml.safe_load(Path(path).read_text()) or {}
        email_data = data.pop("email", {}) or {}
        cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        cfg.email = EmailConfig(
            **{k: v for k, v in email_data.items() if k in EmailConfig.__dataclass_fields__}
        )
        return cfg
