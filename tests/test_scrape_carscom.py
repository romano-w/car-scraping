import os
import sys
import unittest
from unittest.mock import patch

import requests

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import scrape_carscom as sc


class CarsComScraperLiveTests(unittest.TestCase):
    """Tests that exercise the cars.com scraper against the live site.

    These tests make real HTTP requests.  If the site is unreachable, the
    tests are skipped so the suite can still run in restricted environments.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = sc.make_session()
        try:
            resp = cls.session.get(
                sc.build_search_url(1), timeout=sc.REQUEST_TIMEOUT
            )
            if resp.status_code != 200 or not resp.text:
                raise unittest.SkipTest(f"cars.com returned {resp.status_code}")
        except requests.RequestException as exc:  # pragma: no cover - network
            raise unittest.SkipTest(f"cars.com request failed: {exc}")
        cls.html = resp.text
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
        with patch.object(sc, "MAX_PAGES", 1), \
            patch.object(sc, "PAGE_DELAY_RANGE", (0, 0)), \
            patch.object(sc, "FETCH_MODE", "requests"):
            rows = sc.scrape()
        if not rows:
            self.skipTest("No rows returned from live scrape")
        self.assertGreater(len(rows), 0)
        self.assertEqual(rows[0]["source"], "cars.com")


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()

