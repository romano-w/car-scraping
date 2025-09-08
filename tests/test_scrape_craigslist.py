import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import scrape_craigslist as sc

SAMPLE_HTML = """
<html>
  <body>
    <ul class="rows">
      <li class="result-row">
        <a class="result-title" href="https://philadelphia.craigslist.org/cto/d/car-2012-toyota-camry/123.html">2012 Toyota Camry</a>
        <span class="result-price">$3,500</span>
        <span class="result-hood">(Philadelphia)</span>
      </li>
      <li class="result-row">
        <a class="result-title" href="https://philadelphia.craigslist.org/cto/d/car-2002-honda-civic/456.html">2002 Honda Civic</a>
        <span class="result-price">$5,000</span>
        <span class="result-hood">(Philly)</span>
      </li>
    </ul>
  </body>
</html>
"""


class CraigslistScraperTests(unittest.TestCase):
    def test_parse_listings_extracts_fields(self):
        rows = sc.parse_listings(SAMPLE_HTML)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["source"], "craigslist")
        self.assertIn("Toyota Camry", first["title"])
        self.assertEqual(first["price"], 3500)
        self.assertTrue(first["url"].startswith("https://philadelphia.craigslist.org/"))
        self.assertEqual(first["location"], "Philadelphia")

    def test_filter_by_config_applies_limits(self):
        rows = sc.parse_listings(SAMPLE_HTML)
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


if __name__ == "__main__":
    unittest.main()
