# buyer-intent-scraper

Find **publicly available** companies, individuals and organizations that are
*requesting* a service in a given location — with their public contact details —
and export them to **Excel (.xlsx)** (or CSV).

Give it a plain-English query like:

> "who is requesting construction services in Nairobi, Kenya"

It researches the web with **three engines** that feed one deduplicated report:

1. **World Bank procurement API** (`world_bank`) — live, structured notices
   (Invitation for Bids, RFEoI, …) with the procuring entity's contact, the
   **submission deadline**, reference number and category. No API key, no LLM,
   zero tokens — this is the reliable default engine.
2. **Search-engine dorking + portals + directories** (`google_dork`,
   `tender_portal`, `directory`) — Google via SerpAPI or DuckDuckGo (no key),
   targeting buyer-intent keywords (RFQ, tender, "expression of interest", …) on
   sites like `tenders.go.ke`, `businesslist.co.ke`.
3. **Gemini `browser_use` agent** (`agent`, optional) — an LLM that *navigates*
   live pages and returns structured leads. Token-frugal by design (vision off,
   thinking off, seeded onto a results page, few steps). Needs a free Gemini key.

Leads are filtered to **buyers only** (requesting, not offering), **open
contracts only** (past-deadline notices dropped), and the query location;
aggregator domains (biddetail/tenderdetail) are excluded. Each lead carries the
entity name, intent signal, public emails/phones/website, deadline/reference/
category, a confidence score and a source URL.

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Usage

### One-off query

```bash
buyer-intent-scraper scrape "construction services in Nairobi, Kenya" \
  --country-tld ke --require-contact -o out/leads.xlsx -v
```

Writes `out/leads.xlsx` (Excel) and prints a summary of the top leads.

Options: `--format {xlsx,csv,both}` (default `xlsx`), `--sources world_bank
google_dork tender_portal directory agent`, `--max-results`, `--max-leads`,
`--min-confidence`, `--require-contact`, `--include-offering`, `--include-closed`,
`--any-location`, `--include-aggregators`, `--country-tld`, `--ignore-robots`.

### Optional: Gemini browser agent (Engine 3)

```bash
pip install -e ".[agent]"           # installs browser_use (heavy)
export GEMINI_API_KEY=your_free_key  # https://aistudio.google.com/app/apikey
buyer-intent-scraper scrape "construction works in Kenya" --sources agent -v
```

The agent is tuned for **low token usage**: no screenshots (`use_vision=False`),
no chain-of-thought (`use_thinking=False`), `flash_mode`, trimmed history, batched
actions, a small step cap, and it starts on a seeded results page instead of
blind-searching. Model defaults to `gemini-2.5-flash-lite` (cheapest + most
stable on the free tier); change via `agent_model` in config.

### Config-driven run (used by the scheduled automation)

```bash
cp config.example.yaml config.yaml   # edit queries / sources / email
buyer-intent-scraper run config.yaml
# or, without installing:
python scripts/run_scheduled.py config.yaml
```

This writes one file per query plus a combined `*_all-leads.xlsx`, and (optionally)
emails the combined report. The format follows `output_format` in the config
(`xlsx` by default).

## Report columns

`name, entity_type, intent_direction, service, location, intent_signal, emails,
phones, website, deadline, reference, category, source_type, source_title,
source_url, published_date, confidence, discovered_at`

The Excel sheet adds a styled header, clickable `website`/`source_url` links, a
numeric `confidence` column, frozen header row and an auto-filter.

## Configuration (`config.yaml`)

See [`config.example.yaml`](config.example.yaml). Highlights:

- `queries`: list of plain-English queries.
- `sources`: any of `world_bank`, `google_dork`, `tender_portal`, `directory`, `agent`.
- `tender_portals` / `directories`: override the default domain lists.
- `country_tld`: adds `site:.<tld>` dork variants.
- `require_contact`, `min_confidence`: quality filters.
- `only_requesting` (buyers only), `open_only` (drop closed tenders),
  `require_location_match`, `blocklist_domains`: targeting filters (all on by default).
- `agent_model` / `agent_max_steps` / `agent_headless`: Gemini agent tuning.
- `output_format`: `xlsx` (default), `csv`, or `both`.
- `email`: optional SMTP delivery of the combined report.

## Search backend

- **Default:** DuckDuckGo (no key, lower volume / rate-limited).
- **Recommended:** set `SERPAPI_API_KEY` to use Google results via
  [SerpAPI](https://serpapi.com/) for better quality and quota.

## Email (optional)

Set these env vars and `email.enabled: true` in the config — no secrets are
stored in the repo:

```
SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM
```

## Scheduling with Devin

This repo is designed to be run on a cadence by a **scheduled Devin session**
that executes `python scripts/run_scheduled.py config.yaml` and emails the CSV.
See the scheduled session in your Devin workspace.

## Responsible use

This tool only fetches **publicly available** pages, honors `robots.txt` by
default, rate-limits requests, and sends a descriptive User-Agent. It does **not**
access pages behind logins/paywalls or harvest personal data in bulk. You are
responsible for complying with the terms of any site you target and with
applicable data-protection laws (e.g. Kenya's Data Protection Act, GDPR) when
contacting leads.

## Development

```bash
ruff check .
mypy
pytest
```

### Continuous integration

A ready-to-use GitHub Actions workflow (ruff + mypy + pytest) lives at
[`docs/github-actions-ci.yml`](docs/github-actions-ci.yml). Copy it to
`.github/workflows/ci.yml` to enable CI:

```bash
mkdir -p .github/workflows && cp docs/github-actions-ci.yml .github/workflows/ci.yml
```

(It ships under `docs/` because the bot that opened the initial PR lacks the
GitHub `workflow` scope needed to add files under `.github/workflows/`.)
