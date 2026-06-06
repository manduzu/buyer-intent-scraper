# buyer-intent-scraper

Find **publicly available** companies, individuals and organizations that are
*requesting* a service in a given location — with their public contact details —
and export them to **Excel (.xlsx)** (or CSV).

Give it a plain-English query like:

> "who is requesting construction services in Nairobi, Kenya"

and it researches the web via:

1. **Search-engine dorking** (Google via SerpAPI, or DuckDuckGo with no API key) —
   combines the service + location with buyer-intent keywords (RFQ, tender,
   "looking for", "expression of interest", …).
2. **Public tender / procurement portals** (e.g. `tenders.go.ke`, `ppip.go.ke`).
3. **B2B directories & classifieds** (e.g. `businesslist.co.ke`, `jiji.co.ke`).

For each candidate page it extracts the entity name, the intent signal, public
emails/phones/website, classifies the entity type, scores a confidence value,
deduplicates, and writes an Excel report (CSV optional).

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

Options: `--format {xlsx,csv,both}` (default `xlsx`), `--sources google_dork
tender_portal directory`, `--max-results`, `--max-leads`, `--min-confidence`,
`--require-contact`, `--country-tld`, `--ignore-robots`.

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

`name, entity_type, service, location, intent_signal, emails, phones, website,
source_type, source_title, source_url, published_date, confidence, discovered_at`

The Excel sheet adds a styled header, clickable `website`/`source_url` links, a
numeric `confidence` column, frozen header row and an auto-filter.

## Configuration (`config.yaml`)

See [`config.example.yaml`](config.example.yaml). Highlights:

- `queries`: list of plain-English queries.
- `sources`: any of `google_dork`, `tender_portal`, `directory`.
- `tender_portals` / `directories`: override the default domain lists.
- `country_tld`: adds `site:.<tld>` dork variants.
- `require_contact`, `min_confidence`: quality filters.
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
