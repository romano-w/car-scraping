import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import scrape_craigslist as sc

FIXTURE_HTML = (
    Path(__file__).resolve().parent / "fixtures" / "craigslist_page1.html"
).read_text(encoding="utf-8")


class CraigslistScraperTests(unittest.TestCase):
    def test_parse_listings_extracts_fields(self):
        rows = sc.parse_listings(FIXTURE_HTML)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["source"], "craigslist")
        self.assertIn("Toyota Camry", first["title"])
        self.assertEqual(first["price"], 3500)
        self.assertTrue(first["url"].startswith("https://philadelphia.craigslist.org/"))
        self.assertEqual(first["location"], "Philadelphia")

    def test_filter_by_config_applies_limits(self):
        rows = sc.parse_listings(FIXTURE_HTML)
        with patch.object(sc, 'config', autospec=True) as mock_cfg:
            mock_cfg.PRICE_MAX = 4000
            mock_cfg.YEAR_MIN = 2004
            filtered = sc.filter_by_config(rows)
        titles = [r["title"] for r in filtered]
        self.assertTrue(any("Toyota Camry" in t for t in titles))
        self.assertFalse(any("2002" in t for t in titles))

    @patch("requests.Session.get")
    def test_scrape_handles_http_errors(self, mock_get):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = ""
        mock_get.return_value = resp
        with patch.object(sc, 'make_session') as ms:
            ms.return_value = sc.requests.Session()
            rows = sc.scrape()
        self.assertEqual(rows, [])

    @patch("requests.Session.get")
    def test_scrape_returns_rows(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = FIXTURE_HTML
        mock_get.return_value = resp
        with patch.object(sc, 'make_session') as ms, patch.object(sc, 'MAX_PAGES', 1), patch.object(sc, 'PAGE_DELAY_RANGE', (0, 0)):
            ms.return_value = sc.requests.Session()
            rows = sc.scrape()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['source'], 'craigslist')


if __name__ == "__main__":
    unittest.main()
