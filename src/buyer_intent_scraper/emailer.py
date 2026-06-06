"""Optional SMTP emailing of the resulting CSV.

Credentials are read from environment variables so no secrets live in the repo:
``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``, ``EMAIL_FROM``.
"""

from __future__ import annotations

import logging
import os
import smtplib
from collections.abc import Sequence
from email.message import EmailMessage
from pathlib import Path

from buyer_intent_scraper.config import EmailConfig

logger = logging.getLogger(__name__)


def _resolve(value: str) -> str:
    """Resolve a ``${VAR}`` placeholder against the environment."""
    if value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def _mime_for(path: Path) -> tuple[str, str]:
    if path.suffix.lower() == ".xlsx":
        return ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return ("text", "csv")


def send_report(
    attachments: Sequence[str | Path] | str | Path,
    email_config: EmailConfig,
    body: str = "Attached are the latest buyer-intent leads.",
) -> bool:
    """Email one or more report files (xlsx/csv) as attachments.

    Returns True on success.
    """
    if not email_config.enabled:
        logger.info("Email disabled in config; skipping send")
        return False

    recipients = [r for r in email_config.recipients if r]
    if not recipients:
        logger.warning("No recipients configured; skipping email")
        return False

    host = _resolve(email_config.smtp_host)
    user = _resolve(email_config.smtp_user)
    password = _resolve(email_config.smtp_password)
    sender = _resolve(email_config.sender) or user
    if not host or not sender:
        logger.warning("SMTP host/sender not configured; skipping email")
        return False

    items: Sequence[str | Path]
    if isinstance(attachments, (str, Path)):
        items = [attachments]
    else:
        items = attachments
    paths = [Path(p) for p in items]

    msg = EmailMessage()
    msg["Subject"] = email_config.subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    for path in paths:
        maintype, subtype = _mime_for(path)
        msg.add_attachment(
            path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=path.name,
        )

    try:
        with smtplib.SMTP(host, email_config.smtp_port, timeout=30) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        logger.info("Emailed %s to %s", ", ".join(p.name for p in paths), recipients)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email: %s", exc)
        return False
