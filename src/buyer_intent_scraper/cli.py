"""Command-line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from buyer_intent_scraper.config import Config
from buyer_intent_scraper.emailer import send_report
from buyer_intent_scraper.models import Lead
from buyer_intent_scraper.output import write_output
from buyer_intent_scraper.pipeline import run_query


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text]
    slug = "".join(keep).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:60] or "leads"


def _print_summary(leads: list[Lead], out_paths: list[Path]) -> None:
    with_contact = sum(1 for lead in leads if lead.has_contact())
    paths = ", ".join(str(p) for p in out_paths)
    print(f"\nWrote {len(leads)} leads ({with_contact} with contact details) to {paths}")
    for lead in leads[:10]:
        contact = lead.emails[0] if lead.emails else (lead.phones[0] if lead.phones else "-")
        print(f"  [{lead.confidence:.2f}] {lead.name[:50]:50s} {contact}")


def cmd_scrape(args: argparse.Namespace) -> int:
    config = Config(
        sources=args.sources,
        max_results_per_source=args.max_results,
        max_leads_per_query=args.max_leads,
        require_contact=args.require_contact,
        only_requesting=not args.include_offering,
        min_confidence=args.min_confidence,
        respect_robots=not args.ignore_robots,
        country_tld=args.country_tld or "",
        output_format=args.format,
    )
    leads = run_query(args.query, config=config)
    out_base = Path(args.out) if args.out else Path(config.output_dir) / _slug(args.query)
    written = write_output(leads, out_base, fmt=config.output_format)
    _print_summary(leads, written)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    if not config.queries:
        print("No queries configured in config file.", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir or config.output_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    all_leads: list[Lead] = []
    for query in config.queries:
        print(f"\n=== {query} ===")
        leads = run_query(query, config=config)
        all_leads.extend(leads)
        per_query_base = out_dir / f"{stamp}_{_slug(query)}"
        written = write_output(leads, per_query_base, fmt=config.output_format)
        _print_summary(leads, written)

    combined_base = out_dir / f"{stamp}_all-leads"
    combined_written = write_output(all_leads, combined_base, fmt=config.output_format)
    print(f"\nCombined: {len(all_leads)} leads -> {', '.join(str(p) for p in combined_written)}")

    if config.email.enabled:
        send_report(
            combined_written,
            config.email,
            body=f"{len(all_leads)} buyer-intent leads across {len(config.queries)} queries.",
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buyer-intent-scraper",
        description="Find public entities requesting a service in a location, with contacts.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable info logging")
    sub = parser.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("scrape", help="run a single plain-English query")
    sp.add_argument("query", help='e.g. "construction services in Nairobi, Kenya"')
    sp.add_argument("-o", "--out", help="output path (extension set by --format)")
    sp.add_argument(
        "--format",
        default="xlsx",
        choices=["xlsx", "csv", "both"],
        help="output format (default: xlsx)",
    )
    sp.add_argument(
        "--sources",
        nargs="+",
        default=["google_dork", "tender_portal", "directory"],
        choices=["google_dork", "tender_portal", "directory"],
    )
    sp.add_argument("--max-results", type=int, default=10, help="results per source")
    sp.add_argument("--max-leads", type=int, default=50, help="max leads to keep")
    sp.add_argument("--min-confidence", type=float, default=0.0)
    sp.add_argument("--require-contact", action="store_true", help="only keep leads with contacts")
    sp.add_argument(
        "--include-offering",
        action="store_true",
        help="also include providers/sellers (default: only entities requesting)",
    )
    sp.add_argument("--country-tld", default="", help='restrict some dorks to a TLD, e.g. "ke"')
    sp.add_argument("--ignore-robots", action="store_true", help="do not honor robots.txt")
    sp.set_defaults(func=cmd_scrape)

    rp = sub.add_parser("run", help="run all queries from a YAML config file")
    rp.add_argument("config", help="path to config.yaml")
    rp.add_argument("--out-dir", help="override output directory")
    rp.set_defaults(func=cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
