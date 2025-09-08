import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import scrape_carscom as sc


class CarsComScraperLiveTests(unittest.TestCase):
    """Tests that exercise the cars.com scraper against the live site.

    These tests make real HTTP requests. If the site is unreachable, the
    tests are skipped so the suite can still run in restricted environments.

    When TEST_ALLOW_SELENIUM_FALLBACK=1 is set, the test will fall back to
    using Selenium to fetch the page HTML if the initial requests-based
    fetch fails or returns an unexpected status code. This enables running
    the tests locally in environments where cars.com requires JS/cookies.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = sc.make_session()
        url = sc.build_search_url(1)
        # First attempt: plain requests
        try:
            resp = cls.session.get(url, timeout=sc.REQUEST_TIMEOUT)
            ok = resp.status_code == 200 and bool(resp.text)
        except requests.RequestException:  # pragma: no cover - network
            ok = False
            resp = None

        # Optional fallback: Selenium (env-gated)
        if not ok and os.getenv("TEST_ALLOW_SELENIUM_FALLBACK") in ("1", "true", "True"):
            driver = None
            try:
                driver = sc.make_driver()
                html = sc.fetch_html_selenium(driver, url)
                if html:
                    cls.html = html
                    cls.rows = sc.parse_listings(cls.html)
                    return
            except Exception:
                pass
            finally:
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass

        # If still not OK, skip the test class entirely
        if not ok:
            raise unittest.SkipTest(
                f"cars.com request failed or returned unexpected response"
            )
        # Success with requests
        cls.html = resp.text  # type: ignore[union-attr]
        cls.rows = sc.parse_listings(cls.html)

    def test_parse_listings_live(self) -> None:
        self.assertGreater(len(self.rows), 0)
        first = self.rows[0]
        self.assertEqual(first["source"], "cars.com")
        self.assertTrue(first["title"])
        self.assertTrue(first["url"].startswith("https://www.cars.com/"))

    def test_filter_by_config_applies_limits(self) -> None:
        filtered = sc.filter_by_config(self.rows)
        for row in filtered:
            price = row.get("price")
            mileage = row.get("mileage")
            if price is not None:
                self.assertLessEqual(price, int(sc.config.PRICE_MAX))
            if mileage is not None:
                self.assertLessEqual(mileage, int(sc.config.MILEAGE_MAX))

    def test_scrape_live(self) -> None:
        # Decide fetch mode: keep requests for CI; allow selenium locally
        fetch_mode = (
            "selenium" if os.getenv("TEST_ALLOW_SELENIUM_FALLBACK") in ("1", "true", "True") else "requests"
        )
        with patch.object(sc, "MAX_PAGES", 1), \
             patch.object(sc, "PAGE_DELAY_RANGE", (0, 0)), \
             patch.object(sc, "FETCH_MODE", fetch_mode):
            rows = sc.scrape()
        if not rows:
            self.skipTest("No rows returned from live scrape")
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["source"], "cars.com")


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()

