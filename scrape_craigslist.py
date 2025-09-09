import csv
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from utils.throttle import polite_sleep

from utils.url import canonical_url

import config
from utils.http_client import make_session

CRAIGS_DOMAIN = os.getenv("CRAIGS_DOMAIN", getattr(config, "CRAIGS_DOMAIN", "philadelphia"))
BASE_URL = f"https://{CRAIGS_DOMAIN}.craigslist.org/search/cta"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "craigslist_results.csv")
MAX_PAGES = int(os.getenv("CRAIG_MAX_PAGES", "10"))
# Polite delay range between page requests (seconds) for Craigslist
PAGE_DELAY_RANGE: Tuple[float, float] = (3.0, 7.0)
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




def parse_listings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict] = []
    for row in soup.select("li.result-row"):
        link = row.select_one("a.result-title")
        href = link.get("href") if link and link.has_attr("href") else None
        url = urljoin(BASE_URL, href) if href else None
        title = link.get_text(strip=True) if link else None
        
    # Craigslist search pages embed results in a JSON block with id
    # "ld_searchpage_results". Prefer parsing this structured data if
    # available as it is more consistent than scraping DOM elements.
    script = soup.find("script", id="ld_searchpage_results")
    if script and script.string:
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            items = data.get("about") or data.get("itemListElement") or []
            for item in items:
                title = item.get("name")
                url = item.get("url")
                if url and not url.startswith("http"):
                    url = urljoin(BASE_URL, url)
                url = canonical_url(url) if url else None

                price_val = None
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price_val = offers.get("price")
                elif "price" in item:
                    price_val = item.get("price")
                price = clean_number(str(price_val) if price_val is not None else None)

                location = None
                area = item.get("areaServed")
                if isinstance(area, dict):
                    location = area.get("name") or area.get("addressLocality")
                elif isinstance(area, str):
                    location = area

                results.append(
                    {
                        "source": "craigslist",
                        "title": title,
                        "price": price,
                        "mileage": None,
                        "dealer": None,
                        "location": location,
                        "url": url,
                        "first_seen": datetime.utcnow().isoformat(timespec="seconds"),
                    }
                )

    # Fallback to legacy HTML scraping if structured data isn't available
    if not results:
        rows = soup.select("li.result-row")
        for row in rows:
            link = row.select_one("a.result-title")
            href = link.get("href") if link else None
            url = urljoin(BASE_URL, href) if href else None
            url = canonical_url(url) if url else None
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
                    "first_seen": datetime.utcnow().isoformat(timespec="seconds"),
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
    fieldnames = [
        "source",
        "title",
        "price",
        "mileage",
        "dealer",
        "location",
        "url",
        "first_seen",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def scrape() -> List[Dict]:
    all_rows: List[Dict] = []
    use_cache = os.getenv("REQUESTS_CACHE", "0") not in ("0", "false", "False")
    session = make_session(use_cache=use_cache)
    session.headers.update(HEADERS)

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

        polite_sleep(PAGE_DELAY_RANGE)

    return all_rows


def main() -> None:
    rows = scrape()
    rows = filter_by_config(rows)
    print(f"[craigslist] Total listings after filtering: {len(rows)}")
    write_csv(rows, OUTPUT_FILE)
    print(f"[craigslist] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
