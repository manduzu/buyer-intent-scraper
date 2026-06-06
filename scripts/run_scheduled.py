#!/usr/bin/env python3
"""Entry point for the scheduled Devin automation.

Runs every query in ``config.yaml`` (or the path given as the first argument),
writes per-query and combined CSVs into the output directory, and emails the
combined CSV if email is enabled in the config.

Usage:
    python scripts/run_scheduled.py [path/to/config.yaml]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Allow running as a plain script without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from buyer_intent_scraper.cli import cmd_run  # noqa: E402


class _Args:
    def __init__(self, config: str) -> None:
        self.config = config
        self.out_dir = None


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    if not Path(config_path).exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and edit it.", file=sys.stderr)
        return 2
    return cmd_run(_Args(config_path))


if __name__ == "__main__":
    raise SystemExit(main())
