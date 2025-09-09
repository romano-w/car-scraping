import pathlib
import unittest
from datetime import datetime
from unittest.mock import patch

import pytest
import requests

from utils.url import canonical_url

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
        assert first["url"] == canonical_url(first["url"])
        datetime.fromisoformat(first["first_seen"])

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
        sc, "USE_SELENIUM", False
    ):
        try:
            rows = sc.scrape()
        except Exception as exc:  # pragma: no cover - network issues
            pytest.skip(f"Live scrape failed: {exc}")
    if not rows:
        pytest.skip("No rows returned from live scrape")
    assert rows[0]["source"] == "cars.com"
    assert rows[0]["url"] == canonical_url(rows[0]["url"])
    datetime.fromisoformat(rows[0]["first_seen"])


def test_scrape_requests_only():
    dummy_session = object()
    with patch.object(sc, "make_session", return_value=dummy_session), patch.object(
        sc, "fetch_html_requests", return_value="<html></html>"
    ) as fr, patch.object(sc, "parse_listings", return_value=[{"source": "cars.com"}]), patch.object(
        sc, "fetch_html_selenium"
    ) as fs, patch.object(sc, "MAX_PAGES", 1), patch.object(sc, "PAGE_DELAY_RANGE", (0, 0)), patch.object(
        sc, "USE_SELENIUM", False
    ):
        rows = sc.scrape()
    assert fr.called
    fs.assert_not_called()
    assert rows


def test_scrape_selenium_fallback():
    class DummyDriver:
        def quit(self):
            pass

    dummy_session = object()
    dummy_driver = DummyDriver()

    with patch.object(sc, "make_session", return_value=dummy_session), patch.object(
        sc, "fetch_html_requests", return_value="<html></html>"
    ), patch.object(
        sc, "parse_listings", side_effect=[[], [{"source": "cars.com"}]]
    ), patch.object(
        sc, "fetch_html_selenium", return_value="<html></html>"
    ) as fs, patch.object(sc, "make_driver", return_value=dummy_driver), patch.object(
        sc, "MAX_PAGES", 1
    ), patch.object(sc, "PAGE_DELAY_RANGE", (0, 0)), patch.object(sc, "USE_SELENIUM", True):
        rows = sc.scrape()
    assert fs.called
    assert rows
