# Used Car Listings Scraper – Multi-Source, AI-Assisted

Automate gathering used car listings from multiple websites (CarGurus, Cars.com, Craigslist) within a configurable radius, price, year, and mileage. Built to be fast to implement, free to run locally, and assisted by AI for coding (not an autonomous agent).

---

## What this does

- Scrapes major sources for dealer and private listings.
- Respects your criteria (zip, radius, price, year, mileage) from a single config.
- Saves per-source CSVs under `data/`, with an option to merge.
- Minimizes cost and complexity; Selenium is only used if needed.

---

## Data sources and approach

| Source     | Coverage                     | Method                 | Notes |
|------------|------------------------------|------------------------|-------|
| CarGurus   | Dealers + some private       | `requests` → fallback `selenium` | May need modern headers or Selenium for pagination. |
| Cars.com   | Dealers                       | `requests` + `bs4`     | Straightforward static parsing. |
| Craigslist | Private sellers + small lots | `requests` + `bs4`     | Use cars+trucks (by owner and/or dealer). Paginate with `s=120`. |

Optional backups later: Autotrader (via service), Carfax, etc.

---

## Prerequisites

- Python 3.9+
- [uv](https://docs.astral.sh/uv/) for dependency management
- `beautifulsoup4` for HTML parsing

Install dependencies and create a virtual environment with:

```bash
uv sync
```

Run the scrapers through uv (no manual activation needed):

```bash
uv run python scrape_carscom.py
```

---

## Configure your search

Edit `config.py`:

- `ZIP_CODE`: e.g., "22030" for Fairfax, VA (currently set to "19102").
- `RADIUS_MILES`: e.g., 50–200
- `PRICE_MAX`: e.g., 15000
- `MILEAGE_MAX`: e.g., 150000–200000
- `YEAR_MIN`: e.g., 2008+

These values are applied across all scrapers.

---

## Run the scrapers

Run individually; each writes a CSV to `data/`.

```bash
# Cars.com (static; fastest to validate pipeline)
uv run python scrape_carscom.py
# enable Selenium fallback if needed
USE_SELENIUM=1 uv run python scrape_carscom.py

# Craigslist (private sellers)
uv run python scrape_craigslist.py

# CarGurus (try requests first; may auto-fallback to Selenium later)
uv run python scrape_cargurus.py
```

To avoid re-downloading the same pages across runs, enable a local cache by
setting `REQUESTS_CACHE=1`:

```bash
REQUESTS_CACHE=1 uv run python scrape_carscom.py
```

Outputs (by default):

- `data/carscom_results.csv`
- `data/craigslist_results.csv`
- `data/cargurus_results.csv`

---

## Merge results (optional)

A simple merger script can combine per-source CSVs into one master file with a `source` column and basic de-duplication heuristics (e.g., URL or VIN if present). Run it via uv:

```bash
uv run python data/merge_results.py
```

## Run tests

Use uv to execute the test suite with verbose output:

```bash
uv run pytest -v
```

Target: `data/combined_listings.csv`

---

## Scraping etiquette and reliability

- Add small random delays between requests (1–5s) and between pages (2–7s).
- Use reasonable page limits; stop when no new results.
- Rotate a modern `User-Agent` header; back off on HTTP 429/403.
- Prefer `requests` for static sites; use Selenium only where necessary (e.g., CarGurus pagination).
- Keep it personal-use and respect each site’s Terms of Service.

Selenium note: if needed, `webdriver-manager` will fetch the driver automatically; you’ll need a local Chrome/Chromium installed.

---

## Roadmap (fast track)

### Day 1

- Finalize `config.py` criteria.
- Implement/test Cars.com and Craigslist parsers; save CSVs.
- Prototype CarGurus with `requests`; add Selenium fallback if required.

### Day 2

- Full runs with polite rate limiting.
- Optional merge step and quick sanity checks (price/year/mileage filters).
- Triage issues; if a site blocks, slow down or temporarily skip.

Fallback: If a site is unexpectedly difficult, pause it and proceed with the others first; consider a third-party scraper service only as a last resort.

---

## Notes

- Output is intended for manual evaluation and outreach via listing URLs (no scraping of hidden contact info).
- This project uses AI to accelerate coding only; you remain in control of runs and outputs.
