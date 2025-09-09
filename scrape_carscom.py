import csv
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

# New imports for Selenium fallback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait  # fixed import
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from utils.url import canonical_url
from utils.throttle import polite_sleep

import config
from utils.http_client import USER_AGENTS, make_session

BASE_URL = "https://www.cars.com/shopping/results/"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Avoid brotli as many Python stacks lack brotli decoder
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.cars.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "carscom_results.csv")
MAX_PAGES = int(os.getenv("CARS_MAX_PAGES", "10"))  # safety cap
# Polite delay range between page requests (seconds) for cars.com
PAGE_DELAY_RANGE: Tuple[float, float] = (2.0, 6.0)
REQUEST_TIMEOUT = int(os.getenv("CARS_TIMEOUT", "45"))
USE_SELENIUM = os.getenv("USE_SELENIUM", "0") not in ("0", "false", "False", "")
SELENIUM_WAIT = int(os.getenv("CARS_SELENIUM_WAIT", "12"))
PAGE_SIZE = int(os.getenv("CARS_PAGE_SIZE", "50"))


def build_search_url(page: int) -> str:
    params = {
        "stock_type": "used",
        "maximum_distance": config.RADIUS_MILES,
        "zip": config.ZIP_CODE,
        "list_price_max": config.PRICE_MAX,
        "mileage_max": config.MILEAGE_MAX,
        "year_min": config.YEAR_MIN,
        "page": page,
        "page_size": PAGE_SIZE,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def clean_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None




def make_driver() -> webdriver.Chrome:
    opts = ChromeOptions()
    if os.getenv("HEADLESS", "1") not in ("0", "false", "False"):
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1365,1024")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    driver = webdriver.Chrome(ChromeDriverManager().install(), options=opts)
    driver.set_page_load_timeout(REQUEST_TIMEOUT)
    return driver


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
        url = canonical_url(url) if url else None

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
                "first_seen": datetime.utcnow().isoformat(timespec="seconds"),
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


def fetch_html_requests(session: requests.Session, url: str) -> Optional[str]:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text
        print(f"[cars.com] HTTP {resp.status_code} for {url}")
        return None
    except requests.RequestException as e:
        print(f"[cars.com] requests error: {e}")
        return None


def fetch_html_selenium(driver: webdriver.Chrome, url: str) -> Optional[str]:
    try:
        driver.get(url)
        # Wait for at least one vehicle-card to appear, or a results container
        WebDriverWait(driver, SELENIUM_WAIT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".vehicle-card, article.vehicle-card"))
        )
        return driver.page_source
    except Exception as e:
        print(f"[cars.com] selenium error: {e}")
        return None


def scrape() -> List[Dict]:
    all_rows: List[Dict] = []
    use_cache = os.getenv("REQUESTS_CACHE", "0") not in ("0", "false", "False")
    session = make_session(use_cache=use_cache)
    # In tests, make_session may be mocked to a dummy object without headers
    if hasattr(session, "headers") and isinstance(getattr(session, "headers", None), dict):
        session.headers.update(HEADERS)
    driver: Optional[webdriver.Chrome] = None

    # Warm-up: hit homepage to establish cookies/session
    try:
        if hasattr(session, "get"):
            _ = session.get("https://www.cars.com/", timeout=min(REQUEST_TIMEOUT, 20))
    except Exception:
        pass

    for page in range(1, MAX_PAGES + 1):
        url = build_search_url(page)
        print(f"[cars.com] Fetching page {page}: {url}")

        html = fetch_html_requests(session, url)
        page_rows: List[Dict] = parse_listings(html) if html else []

        if not page_rows and USE_SELENIUM:
            if driver is None:
                driver = make_driver()
            html = fetch_html_selenium(driver, url)
            page_rows = parse_listings(html) if html else []

        if not page_rows:
            reason = "Failed to fetch" if not html else "No results found"
            print(f"[cars.com] {reason} on page {page}; stopping.")
            break

        print(f"[cars.com] Parsed {len(page_rows)} listings from page {page}.")
        all_rows.extend(page_rows)

        # Polite delay between pages
        polite_sleep(PAGE_DELAY_RANGE)

    if driver:
        try:
            driver.quit()
        except Exception:
            pass

    return all_rows


def main() -> None:
    rows = scrape()
    rows = filter_by_config(rows)
    print(f"[cars.com] Total listings after filtering: {len(rows)}")
    write_csv(rows, OUTPUT_FILE)
    print(f"[cars.com] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
