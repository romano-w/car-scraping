import csv
import os
import random
import time
from typing import Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

BASE_URL = "https://philadelphia.craigslist.org/search/cto"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "craigslist_results.csv")
MAX_PAGES = int(os.getenv("CRAIG_MAX_PAGES", "10"))
PAGE_DELAY_RANGE = (3.0, 7.0)
REQUEST_TIMEOUT = int(os.getenv("CRAIG_TIMEOUT", "45"))


def build_search_url(page: int) -> str:
    offset = (page - 1) * 120
    params = {
        "postal": config.ZIP_CODE,
        "search_distance": config.RADIUS_MILES,
        "max_price": config.PRICE_MAX,
        "auto_year_min": config.YEAR_MIN,
        "auto_miles_max": config.MILEAGE_MAX,
        "s": offset,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def clean_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_listings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = soup.select("li.result-row")
    results: List[Dict] = []

    for row in rows:
        link = row.select_one("a.result-title")
        href = link.get("href") if link else None
        url = urljoin(BASE_URL, href) if href else None
        title = link.get_text(strip=True) if link else None

        price_el = row.select_one("span.result-price")
        price_text = price_el.get_text(strip=True) if price_el else None
        price = clean_number(price_text)

        hood_el = row.select_one("span.result-hood")
        location = hood_el.get_text(strip=True).strip("()") if hood_el else None

        if not url and not title:
            continue

        results.append(
            {
                "source": "craigslist",
                "title": title,
                "price": price,
                "mileage": None,
                "dealer": None,
                "location": location,
                "url": url,
            }
        )

    return results


def filter_by_config(rows: List[Dict]) -> List[Dict]:
    filtered: List[Dict] = []
    for r in rows:
        if r.get("price") is not None and r["price"] > int(config.PRICE_MAX):
            continue
        year_ok = True
        title = r.get("title") or ""
        year_digits = "".join(ch for ch in title[:4] if ch.isdigit())
        if len(year_digits) == 4:
            try:
                if int(year_digits) < int(config.YEAR_MIN):
                    year_ok = False
            except ValueError:
                pass
        if not year_ok:
            continue
        filtered.append(r)
    return filtered


def write_csv(rows: List[Dict], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = ["source", "title", "price", "mileage", "dealer", "location", "url"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def scrape() -> List[Dict]:
    all_rows: List[Dict] = []
    session = make_session()

    for page in range(1, MAX_PAGES + 1):
        url = build_search_url(page)
        print(f"[craigslist] Fetching page {page}: {url}")
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"[craigslist] Request error on page {page}: {e}")
            break

        if resp.status_code != 200:
            print(f"[craigslist] HTTP {resp.status_code} on page {page}; stopping.")
            break

        page_rows = parse_listings(resp.text)
        if not page_rows:
            print(f"[craigslist] No results found on page {page}; stopping.")
            break

        print(f"[craigslist] Parsed {len(page_rows)} listings from page {page}.")
        all_rows.extend(page_rows)

        time.sleep(random.uniform(*PAGE_DELAY_RANGE))

    return all_rows


def main() -> None:
    rows = scrape()
    rows = filter_by_config(rows)
    print(f"[craigslist] Total listings after filtering: {len(rows)}")
    write_csv(rows, OUTPUT_FILE)
    print(f"[craigslist] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
