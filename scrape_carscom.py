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

BASE_URL = "https://www.cars.com/shopping/results/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.cars.com/",
    "Connection": "keep-alive",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "carscom_results.csv")
MAX_PAGES = int(os.getenv("CARS_MAX_PAGES", "10"))  # safety cap
PAGE_DELAY_RANGE = (2.0, 6.0)
REQUEST_TIMEOUT = int(os.getenv("CARS_TIMEOUT", "45"))


def build_search_url(page: int) -> str:
    params = {
        "stock_type": "used",
        "maximum_distance": config.RADIUS_MILES,
        "zip": config.ZIP_CODE,
        "list_price_max": config.PRICE_MAX,
        "mileage_max": config.MILEAGE_MAX,
        "year_min": config.YEAR_MIN,
        "page": page,
        "page_size": 100,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def clean_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def make_session() -> requests.Session:
    session = requests.Session()
    # Ignore any proxy settings from the execution environment.  The
    # sandbox used for automated tests sets proxy-related environment
    # variables that lead to connection failures (HTTP 403 via a proxy
    # tunnel).  ``requests`` picks these up by default, so we explicitly
    # disable this behaviour to make direct connections instead.
    session.trust_env = False
    session.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=2,  # integer to satisfy linter type
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
    cards = soup.select(".vehicle-card, article.vehicle-card")
    results: List[Dict] = []
    seen_urls = set()

    for card in cards:
        # URL
        link = card.select_one('a.vehicle-card-link, a[href*="/vehicledetail/"]')
        href_val = link.get("href") if link else None
        if isinstance(href_val, list):
            href_val = href_val[0] if href_val else None
        href = href_val if isinstance(href_val, str) else None
        url = urljoin("https://www.cars.com", href) if href else None

        # Title
        title_el = card.select_one("h2, a.vehicle-card-link")
        title = title_el.get_text(strip=True) if title_el else None

        # Price
        price_el = card.select_one(".primary-price, [data-test='vehicleCardPricingBlockPrice']")
        price_text = price_el.get_text(strip=True) if price_el else None
        price = clean_number(price_text)

        # Mileage
        mileage_el = card.select_one(".mileage, [data-test='vehicleMileage']")
        mileage_text = mileage_el.get_text(strip=True) if mileage_el else None
        mileage = clean_number(mileage_text)

        # Dealer / Location (best-effort)
        dealer_el = card.select_one(".dealer-name, [data-test='vehicleCardDealerInfo']")
        dealer = dealer_el.get_text(" ", strip=True) if dealer_el else None

        location_el = card.select_one(
            ".dealer-name__location, .vehicle-card-location, [data-test='vehicleCardLocation']"
        )
        location = location_el.get_text(" ", strip=True) if location_el else None

        if not url and not title:
            continue

        # The markup sometimes nests an <article> with class
        # ``vehicle-card`` inside another element with the same class,
        # which would cause duplicate rows.  Use the listing URL as a
        # simple deduplication key to avoid returning the same car
        # multiple times.
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)

        results.append(
            {
                "source": "cars.com",
                "title": title,
                "price": price,
                "mileage": mileage,
                "dealer": dealer,
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
        if r.get("mileage") is not None and r["mileage"] > int(config.MILEAGE_MAX):
            continue
        # Year filtering from title (best-effort)
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
        print(f"[cars.com] Fetching page {page}: {url}")
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"[cars.com] Request error on page {page}: {e}")
            break

        if resp.status_code != 200:
            print(f"[cars.com] HTTP {resp.status_code} on page {page}; stopping.")
            break

        page_rows = parse_listings(resp.text)
        if not page_rows:
            print(f"[cars.com] No results found on page {page}; stopping.")
            break

        print(f"[cars.com] Parsed {len(page_rows)} listings from page {page}.")
        all_rows.extend(page_rows)

        # Polite delay between pages
        time.sleep(random.uniform(*PAGE_DELAY_RANGE))

    return all_rows


def main() -> None:
    rows = scrape()
    rows = filter_by_config(rows)
    print(f"[cars.com] Total listings after filtering: {len(rows)}")
    write_csv(rows, OUTPUT_FILE)
    print(f"[cars.com] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
