import csv
import json
import os
import random
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

BASE_URL = "https://www.cargurus.com/Cars/inventorylisting/viewDetailsFilterViewInventoryListing.action"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.cargurus.com/",
    "Connection": "keep-alive",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "cargurus_results.csv")
MAX_PAGES = int(os.getenv("CARGURUS_MAX_PAGES", "10"))
PAGE_DELAY_RANGE = (2.0, 6.0)
REQUEST_TIMEOUT = int(os.getenv("CARGURUS_TIMEOUT", "45"))


def build_search_url(page: int) -> str:
    params = {
        "zip": config.ZIP_CODE,
        "radius": config.RADIUS_MILES,
        "maxPrice": config.PRICE_MAX,
        "maxMileage": config.MILEAGE_MAX,
        "minYear": config.YEAR_MIN,
        "inventorySearch": "true",
        "page": page,
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


def _find_listings_in_data(data: Any) -> Optional[List[Dict[str, Any]]]:
    """Recursively search for a list of listing-like dictionaries."""
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data):
            sample = data[0]
            # Heuristic: listings typically include a price or mileage field
            if any(k in sample for k in ("price", "mileage", "canonicalUrl", "title", "name")):
                return data  # type: ignore[return-value]
        for item in data:
            found = _find_listings_in_data(item)
            if found:
                return found
    elif isinstance(data, dict):
        for v in data.values():
            found = _find_listings_in_data(v)
            if found:
                return found
    return None


def _row_from_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build a normalized row dictionary from a listing item."""
    title = (
        item.get("title")
        or item.get("name")
        or item.get("header")
        or item.get("heading")
    )

    price = item.get("price") or item.get("listingPrice") or item.get("priceString")
    price = clean_number(str(price)) if price is not None else None

    mileage = item.get("mileage") or item.get("mileageString")
    mileage = clean_number(str(mileage)) if mileage is not None else None

    dealer = None
    dealer_obj = item.get("dealer")
    if isinstance(dealer_obj, dict):
        dealer = dealer_obj.get("name")
    dealer = dealer or item.get("dealerName") or item.get("sellerName")

    location = None
    if isinstance(dealer_obj, dict):
        location = dealer_obj.get("address") or dealer_obj.get("location")
    location = location or item.get("dealerLocation") or item.get("location")

    url = (
        item.get("canonicalUrl")
        or item.get("url")
        or item.get("link")
        or item.get("detailUrl")
    )
    if url and not str(url).startswith("http"):
        url = urljoin("https://www.cargurus.com", str(url))

    return {
        "source": "cargurus",
        "title": title,
        "price": price,
        "mileage": mileage,
        "dealer": dealer,
        "location": location,
        "url": url,
    }


def parse_listings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict] = []

    # Attempt to find JSON data embedded in script tags
    for script in soup.find_all("script"):
        text = script.string or ""
        if "{" not in text:
            continue
        candidate = text.strip()
        if "=" in candidate and not candidate.strip().startswith("{"):
            # e.g., window.__DATA__ = {...};
            candidate = candidate.split("=", 1)[1].strip()
        candidate = candidate.strip(";\n ")
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        listings = _find_listings_in_data(data)
        if listings:
            for item in listings:
                results.append(_row_from_item(item))
            if results:
                return results

    # Fallback to parsing visible HTML cards
    cards = soup.select(
        "[data-test='inventory-listing'], [data-cg-ft='inventory-listing'], div[data-listingid]"
    )

    for card in cards:
        link = card.select_one("a[data-test='listing-link'], a[itemprop='url'], a[href]")
        href_val = link.get("href") if link else None
        if isinstance(href_val, list):
            href_val = href_val[0] if href_val else None
        href = href_val if isinstance(href_val, str) else None
        url = urljoin("https://www.cargurus.com", href) if href else None

        title = link.get_text(strip=True) if link else None

        price_el = card.select_one(
            "[data-test='listing-price'], [itemprop='price'], [data-cg-ft='listing-price']"
        )
        price_text = price_el.get_text(strip=True) if price_el else None
        price = clean_number(price_text)

        mileage_el = card.select_one(
            "[data-test='mileage'], [data-test='listing-mileage'], [itemprop='mileage']"
        )
        mileage_text = mileage_el.get_text(strip=True) if mileage_el else None
        mileage = clean_number(mileage_text)

        dealer_el = card.select_one(
            "[data-test='dealer-name'], [itemprop='seller'], [data-cg-ft='dealer-name']"
        )
        dealer = dealer_el.get_text(strip=True) if dealer_el else None

        location_el = card.select_one(
            "[data-test='dealer-address'], [data-test='listing-location'], [itemprop='address']"
        )
        location = location_el.get_text(strip=True) if location_el else None

        if not url and not title:
            continue

        results.append(
            {
                "source": "cargurus",
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
        title = r.get("title") or ""
        year_ok = True
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
        print(f"[cargurus] Fetching page {page}: {url}")
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"[cargurus] Request error on page {page}: {e}")
            break

        if resp.status_code != 200:
            print(f"[cargurus] HTTP {resp.status_code} on page {page}; stopping.")
            break

        page_rows = parse_listings(resp.text)
        if not page_rows:
            print(f"[cargurus] No results found on page {page}; stopping.")
            break

        print(f"[cargurus] Parsed {len(page_rows)} listings from page {page}.")
        all_rows.extend(page_rows)

        time.sleep(random.uniform(*PAGE_DELAY_RANGE))

    return all_rows


def main() -> None:
    rows = scrape()
    rows = filter_by_config(rows)
    print(f"[cargurus] Total listings after filtering: {len(rows)}")
    write_csv(rows, OUTPUT_FILE)
    print(f"[cargurus] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
