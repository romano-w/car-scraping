import csv
import os
import json
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
from utils.console import console
from functools import partial

print = partial(console.print, style="magenta", markup=False)

CRAIGS_DOMAIN = os.getenv("CRAIGS_DOMAIN", getattr(config, "CRAIGS_DOMAIN", "philadelphia"))
# Domain base for URL joins
BASE_DOMAIN = f"https://{CRAIGS_DOMAIN}.craigslist.org"
# Use 'cto' (cars+trucks by owner) as default to match recorded cassette and tests
BASE_URL = f"{BASE_DOMAIN}/search/cto"
# Optional category control via env: CRAIG_CATEGORIES=cto,cta or "both"
_cats_env = os.getenv("CRAIG_CATEGORIES", "both").lower().strip()
if _cats_env in ("both", "all"):
    CRAIG_CATEGORIES = ["cto", "cta"]
else:
    CRAIG_CATEGORIES = [c.strip() for c in _cats_env.split(",") if c.strip() in ("cto", "cta")] or ["cto"]
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "craigslist_results.csv")
MAX_PAGES = int(os.getenv("CRAIG_MAX_PAGES", "9999"))
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


def build_search_url_for_category(category: str, page: int) -> str:
    """Explicit category version used when iterating multiple categories."""
    offset = (page - 1) * 120
    params = {
        "postal": config.ZIP_CODE,
        "search_distance": config.RADIUS_MILES,
        "max_price": config.PRICE_MAX,
        "auto_year_min": config.YEAR_MIN,
        "auto_miles_max": config.MILEAGE_MAX,
        "s": offset,
    }
    return f"{BASE_DOMAIN}/search/{category}?{urlencode(params)}"


def clean_number(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None




def parse_listings(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    results: List[Dict] = []
    seen_urls = set()

    # Craigslist search pages embed results in a JSON block with id
    # "ld_searchpage_results". Prefer parsing this structured data if
    # available as it is more consistent than scraping DOM elements.
    script = soup.find("script", id="ld_searchpage_results") or soup.find(
        "script", attrs={"type": "application/ld+json"}
    )
    if script and script.string:
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            items = data.get("itemListElement") or data.get("about") or []
            for entry in items:
                # itemListElement is often an array of ListItem with "item" nested
                item = entry.get("item") if isinstance(entry, dict) and "item" in entry else entry
                if not isinstance(item, dict):
                    continue
                title = item.get("name") or item.get("headline")
                url = item.get("url") or item.get("@id")
                if url and not url.startswith("http"):
                    url = urljoin(BASE_DOMAIN, url)
                url = canonical_url(url) if url else None

                # Guard against empty rows
                if not url and not title:
                    continue

                price_val = None
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price_val = offers.get("price")
                elif "price" in item:
                    price_val = item.get("price")
                price = clean_number(str(price_val) if price_val is not None else None)

                location = None
                area = item.get("areaServed") or item.get("address")
                if isinstance(area, dict):
                    location = area.get("name") or area.get("addressLocality") or area.get("addressRegion")
                elif isinstance(area, str):
                    location = area

                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)

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
        rows = soup.select("li.result-row, li.cl-search-result")
        for row in rows:
            link = row.select_one("a.result-title, a.hdrlnk")
            href = link.get("href") if link else None
            url = urljoin(BASE_DOMAIN, href) if href else None
            url = canonical_url(url) if url else None
            title = link.get_text(strip=True) if link else None

            price_el = row.select_one("span.result-price, span.price")
            price_text = price_el.get_text(strip=True) if price_el else None
            price = clean_number(price_text)

            hood_el = row.select_one("span.result-hood, span.nearby")
            location = hood_el.get_text(strip=True).strip("()") if hood_el else None

            if not url and not title:
                continue

            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

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


def dedupe_rows(rows: List[Dict]) -> List[Dict]:
    seen: set = set()
    out: List[Dict] = []
    for r in rows:
        u = r.get("url")
        if not u:
            out.append(r)
            continue
        if u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def _numeric_stats(values: List[Optional[int]]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    nums = [v for v in values if isinstance(v, int)]
    if not nums:
        return None, None, None
    nums_sorted = sorted(nums)
    mn = nums_sorted[0]
    mid = len(nums_sorted) // 2
    if len(nums_sorted) % 2 == 1:
        med = nums_sorted[mid]
    else:
        med = int((nums_sorted[mid - 1] + nums_sorted[mid]) / 2)
    avg = int(sum(nums_sorted) / len(nums_sorted))
    return mn, med, avg


def _fmt_int(n: Optional[int]) -> str:
    return f"{n:,}" if isinstance(n, int) else "n/a"


def _fmt_currency(n: Optional[int]) -> str:
    return f"${n:,}" if isinstance(n, int) else "n/a"


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
    start_ts = time.time()
    use_cache = os.getenv("REQUESTS_CACHE", "0") not in ("0", "false", "False")
    session = make_session(use_cache=use_cache)
    session.headers.update(HEADERS)

    # Run header
    cats_str = ",".join(CRAIG_CATEGORIES)
    print("[craigslist] ── Run ────────────────────────────────────────────────")
    print(f"[craigslist] Domain: {CRAIGS_DOMAIN} • Categories: {cats_str} • Pages per category: {MAX_PAGES}")
    print(f"[craigslist] Zip {config.ZIP_CODE} • Radius {config.RADIUS_MILES}mi • Year ≥ {config.YEAR_MIN} • Price ≤ ${int(config.PRICE_MAX):,} • Miles ≤ {int(config.MILEAGE_MAX):,}")

    cumulative = 0
    for category in CRAIG_CATEGORIES:
        for page in range(1, MAX_PAGES + 1):
            url = build_search_url_for_category(category, page)
            print(f"[craigslist] {category} page {page}/{MAX_PAGES} → {url}")
            try:
                resp = session.get(url, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as e:
                print(f"[craigslist] Request error on {category} page {page}: {e}")
                break

            if resp.status_code != 200:
                print(f"[craigslist] HTTP {resp.status_code} on {category} page {page}; stopping this category.")
                break

            page_rows = parse_listings(resp.text)
            if not page_rows:
                print(f"[craigslist] No results found on {category} page {page}; stopping this category.")
                break

            cumulative += len(page_rows)
            elapsed = _fmt_duration(time.time() - start_ts)
            print(f"[craigslist] ✓ Parsed {len(page_rows)} on {category} page {page} • cumulative {cumulative} • elapsed {elapsed}")
            all_rows.extend(page_rows)

            polite_sleep(PAGE_DELAY_RANGE)

    # Deduplicate across categories/pages before returning
    return dedupe_rows(all_rows)


def main() -> None:
    rows = scrape()
    total_raw = len(rows)
    deduped = dedupe_rows(rows)
    dropped_dupes = total_raw - len(deduped)

    # Quick stats before filtering
    price_min, price_med, price_avg_int = _numeric_stats([r.get("price") for r in deduped])
    missing_title = sum(1 for r in deduped if not (r.get("title") or "").strip())
    missing_location = sum(1 for r in deduped if not (r.get("location") or "").strip())

    print("[craigslist] ── Summary (raw) ───────────────────────────────────────")
    print(f"[craigslist] Total rows: {total_raw} • Unique by URL: {len(deduped)} • Duplicates dropped: {dropped_dupes}")
    print(f"[craigslist] Price: min {_fmt_currency(price_min)} • median {_fmt_currency(price_med)} • avg {_fmt_currency(price_avg_int)}")
    print(f"[craigslist] Missing title: {missing_title} • Missing location: {missing_location}")

    filtered = filter_by_config(deduped)
    print("[craigslist] ── Summary (filtered) ──────────────────────────────────")
    print(f"[craigslist] Rows after filtering: {len(filtered)} (dropped {len(deduped) - len(filtered)})")
    f_price_min, f_price_med, f_price_avg_int = _numeric_stats([r.get("price") for r in filtered])
    print(f"[craigslist] Price: min {_fmt_currency(f_price_min)} • median {_fmt_currency(f_price_med)} • avg {_fmt_currency(f_price_avg_int)}")

    write_csv(filtered, OUTPUT_FILE)
    print(f"[craigslist] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
