import pytest
import requests
from datetime import datetime

import scrape_carscom as sc


@pytest.mark.live
@pytest.mark.vcr
@pytest.mark.default_cassette("carscom_one_page")
def test_carscom_one_page() -> None:
    url = sc.build_search_url(1)
    session = sc.requests.Session()
    session.headers.update(sc.HEADERS)
    try:
        resp = session.get(url, timeout=sc.REQUEST_TIMEOUT, proxies={"http": "", "https": ""})
    except requests.RequestException as exc:  # pragma: no cover - network
        pytest.skip(f"cars.com request failed: {exc}")
    assert resp.status_code == 200
    rows = sc.parse_listings(resp.text)
    assert rows and rows[0]["source"] == "cars.com"
    assert "?" not in rows[0]["url"] and "#" not in rows[0]["url"]
    datetime.fromisoformat(rows[0]["first_seen"])
