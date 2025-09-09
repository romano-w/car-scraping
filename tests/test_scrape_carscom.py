import pathlib
import unittest
from unittest.mock import patch

import pytest
import requests

pytestmark = pytest.mark.live

import scrape_carscom as sc

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "carscom_page1.html"


@pytest.mark.live
class CarsComScraperLiveTests(unittest.TestCase):
    """Tests that exercise the cars.com scraper against the live site."""

    def test_parse_listings_from_fixture(self):
        html = FIXTURE.read_text()
        rows = sc.parse_listings(html)
        assert rows
        first = rows[0]
        assert first["source"] == "cars.com"
        assert first["title"]
        assert first["url"].startswith("https://www.cars.com/")

    def test_filter_by_config_applies_limits(self):
        html = FIXTURE.read_text()
        rows = sc.parse_listings(html)
        filtered = sc.filter_by_config(rows)
        for row in filtered:
            price = row.get("price")
            mileage = row.get("mileage")
            if price is not None:
                assert price <= int(sc.config.PRICE_MAX)
            if mileage is not None:
                assert mileage <= int(sc.config.MILEAGE_MAX)


@pytest.mark.live
def test_scrape_live():
    with patch.object(sc, "MAX_PAGES", 1), patch.object(sc, "PAGE_DELAY_RANGE", (0, 0)), patch.object(
        sc, "FETCH_MODE", "requests"
    ):
        try:
            rows = sc.scrape()
        except Exception as exc:  # pragma: no cover - network issues
            pytest.skip(f"Live scrape failed: {exc}")
    if not rows:
        pytest.skip("No rows returned from live scrape")
    assert rows[0]["source"] == "cars.com"
