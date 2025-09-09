import os
import types
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import scrape_cargurus as cg


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cargurus_page1.html"
HTML = FIXTURE_PATH.read_text(encoding="utf-8")


class CarGurusScraperTests(unittest.TestCase):
    def test_parse_listings_extracts_fields(self):
        rows = cg.parse_listings(HTML)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["source"], "cargurus")
        self.assertIn("Toyota Camry", first["title"])
        self.assertEqual(first["price"], 8999)
        self.assertEqual(first["mileage"], 123456)
        self.assertTrue(first["url"].startswith("https://www.cargurus.com/Cars/"))
        self.assertEqual(first["dealer"], "Best Dealer")
        self.assertIn("Philadelphia", first["location"])

    def test_filter_by_config_applies_limits(self):
        rows = cg.parse_listings(HTML)
        with patch.object(cg, "config", autospec=True) as mock_cfg:
            mock_cfg.PRICE_MAX = 9000
            mock_cfg.MILEAGE_MAX = 200000
            mock_cfg.YEAR_MIN = 2004
            filtered = cg.filter_by_config(rows)
        titles = [r["title"] for r in filtered]
        self.assertTrue(any("Toyota Camry" in t for t in titles))
        self.assertFalse(any("2002" in t for t in titles))

    @patch("requests.Session.get")
    def test_scrape_handles_http_errors(self, mock_get):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = ""
        mock_get.return_value = resp
        with patch.object(cg, "make_session") as ms:
            ms.return_value = cg.requests.Session()
            rows = cg.scrape()
        self.assertEqual(rows, [])

    @patch("requests.Session.get")
    def test_scrape_returns_rows(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = HTML
        mock_get.return_value = resp
        with patch.object(cg, "make_session") as ms, patch.object(cg, "MAX_PAGES", 1), patch.object(cg, "PAGE_DELAY_RANGE", (0, 0)):
            ms.return_value = cg.requests.Session()
            rows = cg.scrape()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source"], "cargurus")


if __name__ == "__main__":
    unittest.main()
