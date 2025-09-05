# Used Car Listings Scraper – Multi-Source, AI-Assisted

This project automates the process of gathering **used car listings** from multiple websites (CarGurus, Cars.com, Craigslist) within a **200-mile radius** of a given location, under a given **price** and **mileage** limit.

The goal is to quickly build a **comprehensive dataset** of vehicles for evaluation and offers, using **AI-assisted coding** for fast development but keeping the workflow under your control.

---

## Project Goals
- Aggregate used car listings from major dealer and private sale websites.
- Run on **local or lightweight cloud environments** with no extra cost.
- Use **AI tools** (ChatGPT, VSCode Copilot) to accelerate coding, but avoid full autonomous agents for reliability.
- Deliver a **CSV or Airtable dataset** for easy filtering, sorting, and contacting sellers.

---

## Data Sources
| Source       | Coverage                  | Method            | Notes                                     |
|---------------|----------------------------|-------------------|-------------------------------------------|
| CarGurus       | Dealers, some private      | `requests` or `selenium` | Provides deal ratings, big inventory.      |
| Cars.com       | Dealers                    | `requests`        | Simple HTML parsing, well-documented.      |
| Craigslist     | Private sellers, local lots| `requests`        | Focus on `cars+trucks` category by owner.  |

Optional backups:
- Autotrader (Apify scraper exists)
- Carfax (has official scraper on Apify)
- eBay Motors, TrueCar, etc. (future expansion)

---

## Tech Stack

- **Python 3.9+**
- **Libraries**:
  - `requests`, `beautifulsoup4`, `lxml` – for HTTP requests and HTML parsing
  - `selenium`, `webdriver-manager` – for dynamic pages (CarGurus if needed)
  - `pandas` – for cleaning, merging, CSV export
  - `time`, `random` – for polite scraping delays
- **AI Tools** (for coding help only):
  - ChatGPT / Copilot in VSCode
  - GPT-4 for generating parsing logic, troubleshooting
- **Data Output**:
  - CSV files per source
  - Optional merge into a single CSV or Airtable base

---

## Quick Start

### 1. Setup Environment
```bash
python3 -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
