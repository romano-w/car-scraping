import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(__file__)))
import scrape_carscom as sc

SAMPLE_HTML = """
<html>
  <body>
    <article class="vehicle-card">
      <a class="vehicle-card-link" href="/vehicledetail/abcd1234">2012 Toyota Camry</a>
      <div class="primary-price">$8,999</div>
      <div class="mileage">123,456 mi.</div>
      <div class="dealer-name">Best Dealer</div>
      <div class="vehicle-card-location">Philadelphia, PA</div>
    </article>
    <article class="vehicle-card">
      <a class="vehicle-card-link" href="/vehicledetail/efgh5678">2002 Honda Civic</a>
      <div class="primary-price">$3,500</div>
      <div class="mileage">200,001 mi.</div>
      <div class="dealer-name">Good Cars</div>
      <div class="vehicle-card-location">Philly, PA</div>
    </article>
  </body>
</html>
"""

class CarsComScraperTests(unittest.TestCase):
    def test_parse_listings_extracts_fields(self):
        rows = sc.parse_listings(SAMPLE_HTML)
        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first["source"], "cars.com")
        self.assertIn("Toyota Camry", first["title"])  # title presence
        self.assertTrue(first["price"] == 8999)
        self.assertTrue(first["mileage"] == 123456)
        self.assertTrue(first["url"].startswith("https://www.cars.com/vehicledetail/"))
        self.assertEqual(first["dealer"], "Best Dealer")
        self.assertIn("Philadelphia", first["location"])  # best-effort

    def test_filter_by_config_applies_limits(self):
        # Two rows: one valid, one over mileage and below year
        rows = sc.parse_listings(SAMPLE_HTML)
        # Override config dynamically for the test
        with patch.object(sc, 'config', autospec=True) as mock_cfg:
            mock_cfg.PRICE_MAX = 9000
            mock_cfg.MILEAGE_MAX = 200000
            mock_cfg.YEAR_MIN = 2004
            filtered = sc.filter_by_config(rows)
        # Civic 2002 should be filtered out by YEAR_MIN via title heuristic
        titles = [r["title"] for r in filtered]
        self.assertTrue(any("Toyota Camry" in t for t in titles))
        self.assertFalse(any("2002" in t for t in titles))

    @patch("requests.Session.get")
    def test_scrape_handles_http_errors(self, mock_get):
        # Simulate non-200 status to break the loop gracefully
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
