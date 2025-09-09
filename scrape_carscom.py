import csv
import os
import random
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urljoin
import statistics

import requests
from bs4 import BeautifulSoup

# New imports for Selenium fallback
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait  # fixed import
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.remote.webdriver import WebDriver as SeleniumWebDriver

from utils.url import canonical_url
from utils.throttle import polite_sleep

import config
from utils.http_client import USER_AGENTS, make_session

BASE_URL = "https://www.cars.com/shopping/results/"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Keep encoding realistic but avoid br to not require brotli locally
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.cars.com/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "DNT": "1",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    # Additional browser-like client hints and fetch headers
    "sec-ch-ua": '"Chromium";v="127", "Not;A=Brand";v="24", "Google Chrome";v="127"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
}

OUTPUT_DIR = "data"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "carscom_results.csv")
# High default so we capture all pages unless overridden via env
MAX_PAGES = int(os.getenv("CARS_MAX_PAGES", "9999"))
# Polite delay range between page requests (seconds) for cars.com
PAGE_DELAY_RANGE: Tuple[float, float] = (2.0, 6.0)
REQUEST_TIMEOUT = int(os.getenv("CARS_TIMEOUT", "45"))
USE_SELENIUM = os.getenv("USE_SELENIUM", "0") not in ("0", "false", "False", "")
# Automatically fall back to Selenium on failures or bot checks unless disabled
AUTO_SELENIUM_ON_FAIL = os.getenv("AUTO_SELENIUM_ON_FAIL", "1") not in ("0", "false", "False", "")
SELENIUM_WAIT = int(os.getenv("CARS_SELENIUM_WAIT", "12"))
PAGE_SIZE = int(os.getenv("CARS_PAGE_SIZE", "50"))
BROWSER = os.getenv("BROWSER", "auto").lower()  # 'chrome', 'edge', or 'auto'


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




def _locate_chrome_windows() -> Optional[str]:
    """Try to find Chrome binary on Windows typical install paths."""
    candidates = [
        # Stable
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        # Dev
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome Dev\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome Dev\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome Dev\Application\chrome.exe"),
        # Beta
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome Beta\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome Beta\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome Beta\Application\chrome.exe"),
        # Canary
        os.path.expandvars(r"%LocalAppData%\Google\Chrome SxS\Application\chrome.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def _locate_edge_windows() -> Optional[str]:
    """Try to find Microsoft Edge binary on Windows typical install paths."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def make_driver() -> SeleniumWebDriver:
    # If user explicitly wants Edge
    if BROWSER == "edge":
        edge_binary = os.getenv("EDGE_BINARY") or (os.name == "nt" and _locate_edge_windows()) or None
        eopts = EdgeOptions()
        if os.getenv("HEADLESS", "1") not in ("0", "false", "False"):
            eopts.add_argument("--headless=new")
        eopts.add_argument("--disable-gpu")
        eopts.add_argument("--no-sandbox")
        eopts.add_argument("--window-size=1365,1024")
        eopts.add_argument("--log-level=3")
        eopts.add_argument("--silent")
        eopts.add_argument("--enable-unsafe-swiftshader")
        eopts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
        if edge_binary:
            eopts.binary_location = edge_binary
        try:
            # Silence EdgeDriver logs
            eservice = EdgeService(EdgeChromiumDriverManager().install(), log_path=os.devnull)
            driver = webdriver.Edge(service=eservice, options=eopts)
        except Exception:
            driver = webdriver.Edge(options=eopts)
        try:
            driver.set_page_load_timeout(REQUEST_TIMEOUT)
        except Exception:
            pass
        return driver

    opts = ChromeOptions()
    if os.getenv("HEADLESS", "1") not in ("0", "false", "False"):
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--window-size=1365,1024")
    opts.add_argument("--log-level=3")
    opts.add_argument("--silent")
    opts.add_argument("--enable-unsafe-swiftshader")
    opts.add_argument(f"--user-agent={random.choice(USER_AGENTS)}")
    # Reduce obvious automation signals
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])  # type: ignore[arg-type]
    opts.add_experimental_option("useAutomationExtension", False)  # type: ignore[arg-type]
    # Allow overriding Chrome binary via env (useful in containers)
    chrome_binary = os.getenv("CHROME_BINARY")
    if chrome_binary:
        opts.binary_location = chrome_binary
    elif os.name == "nt":
        auto = _locate_chrome_windows()
        if auto:
            opts.binary_location = auto

    # Initialize driver: prefer Selenium Manager auto-detect for speed
    try:
        # Prefer Selenium Manager auto-detect and silence logs if possible
        driver = webdriver.Chrome(options=opts)
    except Exception:
        # Fallback to webdriver-manager if needed and silence chromedriver logs
        try:
            service = ChromeService(ChromeDriverManager().install(), log_path=os.devnull)
            driver = webdriver.Chrome(service=service, options=opts)
        except TypeError:
            driver = webdriver.Chrome(options=opts)
    try:
        # Mask webdriver property
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        })
    except Exception:
        pass
    driver.set_page_load_timeout(REQUEST_TIMEOUT)
    return driver


def looks_like_bot_check(html: Optional[str]) -> bool:
    if not html:
        return False
    text = html.lower()
    signals = [
        "are you a human",
        "verify you are human",
        "checking your browser",
        "please enable javascript",
        "captcha",
        "access denied",
        "request blocked",
        "attention required",
        "cf-chl-",
        "just a moment",
    ]
    return any(s in text for s in signals)


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


def dedupe_rows(rows: List[Dict]) -> List[Dict]:
    """Remove duplicate listings across pages by URL, keeping first occurrence."""
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
    """Return (min, median, avg) as ints for a list of optional ints, ignoring None."""
    nums = [v for v in values if isinstance(v, int)]
    if not nums:
        return None, None, None
    nums_sorted = sorted(nums)
    mn = nums_sorted[0]
    med = int(statistics.median(nums_sorted))
    avg = int(statistics.mean(nums_sorted))
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


def fetch_html_selenium(driver: SeleniumWebDriver, url: str) -> Optional[str]:
    try:
        driver.get(url)
        # Attempt to accept cookie banner if present
        # 1) Try common CSS selectors (OneTrust / generic)
        consent_selectors = [
            "button#onetrust-accept-btn-handler",
            "#onetrust-accept-btn-handler",
            "button[aria-label='Accept all cookies']",
            "button[aria-label*='Accept'][aria-label*='cookie']",
        ]
        for sel in consent_selectors:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                if els:
                    try:
                        els[0].click()
                        break
                    except Exception:
                        pass
            except Exception:
                # ignore bad selector issues and keep trying
                continue
        else:
            # 2) Fallback: XPath contains text 'Accept all cookies'
            try:
                xpath_variants = [
                    "//button[contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept all cookies')]",
                    "//button[contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]",
                ]
                for xp in xpath_variants:
                    try:
                        els = driver.find_elements(By.XPATH, xp)
                        if els:
                            try:
                                els[0].click()
                                break
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass
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
    start_ts = time.time()
    use_cache = os.getenv("REQUESTS_CACHE", "0") not in ("0", "false", "False")
    session = make_session(use_cache=use_cache)
    # In tests, make_session may be mocked to a dummy object without headers
    if hasattr(session, "headers") and isinstance(getattr(session, "headers", None), dict):
        session.headers.update(HEADERS)
    driver: Optional[SeleniumWebDriver] = None

    # Warm-up: hit homepage to establish cookies/session
    try:
        if hasattr(session, "get"):
            _ = session.get("https://www.cars.com/", timeout=min(REQUEST_TIMEOUT, 20))
    except Exception:
        pass

    # Run header
    mode = "selenium" if USE_SELENIUM else ("requests + auto-selenium" if AUTO_SELENIUM_ON_FAIL else "requests-only")
    headless = os.getenv("HEADLESS", "1") not in ("0", "false", "False")
    browser = BROWSER
    print("[cars.com] ── Run ─────────────────────────────────────────────────────")
    print(f"[cars.com] Mode: {mode} • Browser: {browser} • Headless: {headless}")
    print(f"[cars.com] Zip {config.ZIP_CODE} • Radius {config.RADIUS_MILES}mi • Year ≥ {config.YEAR_MIN} • Price ≤ ${int(config.PRICE_MAX):,} • Miles ≤ {int(config.MILEAGE_MAX):,}")
    print(f"[cars.com] Pages: {MAX_PAGES} • Page size: {PAGE_SIZE}")

    cumulative = 0
    for page in range(1, MAX_PAGES + 1):
        url = build_search_url(page)
        print(f"[cars.com] Page {page}/{MAX_PAGES} → {url}")

        html: Optional[str]
        page_rows: List[Dict]

        if USE_SELENIUM:
            # Skip requests entirely for speed and to avoid bot timeouts
            if driver is None:
                try:
                    driver = make_driver()
                except Exception as e:
                    print(f"[cars.com] selenium driver init failed: {e}")
                    driver = None
            if driver is not None:
                html = fetch_html_selenium(driver, url)
                page_rows = parse_listings(html) if html else []
            else:
                html = None
                page_rows = []
        else:
            html = fetch_html_requests(session, url)
            page_rows = parse_listings(html) if html else []

        # If requests failed entirely, optionally auto-fallback
        if not page_rows and (html is None) and AUTO_SELENIUM_ON_FAIL:
            if driver is None:
                try:
                    driver = make_driver()
                except Exception as e:
                    print(f"[cars.com] selenium driver init failed: {e}")
                    driver = None
            if driver is not None:
                html = fetch_html_selenium(driver, url)
                page_rows = parse_listings(html) if html else []

        # If HTML looks like a bot-check or empty results, use configured selenium path
        if not page_rows and (USE_SELENIUM or (AUTO_SELENIUM_ON_FAIL and looks_like_bot_check(html))):
            if driver is None:
                try:
                    driver = make_driver()
                except Exception as e:
                    print(f"[cars.com] selenium driver init failed: {e}")
                    driver = None
            if driver is not None:
                html = fetch_html_selenium(driver, url)
                page_rows = parse_listings(html) if html else []

        if not page_rows:
            reason = "Failed to fetch" if not html else "No results found"
            print(f"[cars.com] {reason} on page {page}; stopping.")
            break

        # Per-page progress
        cumulative += len(page_rows)
        elapsed = _fmt_duration(time.time() - start_ts)
        print(f"[cars.com] ✓ Parsed {len(page_rows)} on page {page} • cumulative {cumulative} • elapsed {elapsed}")

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
    total_raw = len(rows)
    # Global de-dup by URL before filtering
    deduped = dedupe_rows(rows)
    dropped_dupes = total_raw - len(deduped)

    # Quick stats before filtering
    price_min, price_med, price_avg_int = _numeric_stats([r.get("price") for r in deduped])
    miles_min, miles_med, miles_avg_int = _numeric_stats([r.get("mileage") for r in deduped])
    missing_dealer = sum(1 for r in deduped if not (r.get("dealer") or "" ).strip())
    missing_location = sum(1 for r in deduped if not (r.get("location") or "").strip())

    print("[cars.com] ── Summary (raw) ───────────────────────────────────────────")
    print(f"[cars.com] Total rows: {total_raw} • Unique by URL: {len(deduped)} • Duplicates dropped: {dropped_dupes}")
    print(f"[cars.com] Price: min {_fmt_currency(price_min)} • median {_fmt_currency(price_med)} • avg {_fmt_currency(price_avg_int)}")
    print(f"[cars.com] Mileage: min {_fmt_int(miles_min)} • median {_fmt_int(miles_med)} • avg {_fmt_int(miles_avg_int)}")
    print(f"[cars.com] Missing dealer: {missing_dealer} • Missing location: {missing_location}")

    # Apply filters from config
    filtered = filter_by_config(deduped)
    print("[cars.com] ── Summary (filtered) ─────────────────────────────────────")
    print(f"[cars.com] Rows after filtering: {len(filtered)} (dropped {len(deduped) - len(filtered)})")
    f_price_min, f_price_med, f_price_avg_int = _numeric_stats([r.get("price") for r in filtered])
    f_miles_min, f_miles_med, f_miles_avg_int = _numeric_stats([r.get("mileage") for r in filtered])
    print(f"[cars.com] Price: min {_fmt_currency(f_price_min)} • median {_fmt_currency(f_price_med)} • avg {_fmt_currency(f_price_avg_int)}")
    print(f"[cars.com] Mileage: min {_fmt_int(f_miles_min)} • median {_fmt_int(f_miles_med)} • avg {_fmt_int(f_miles_avg_int)}")

    write_csv(filtered, OUTPUT_FILE)
    print(f"[cars.com] Wrote CSV: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
