import pytest
import requests
from datetime import datetime

import scrape_cargurus as cg


@pytest.mark.live
@pytest.mark.vcr
@pytest.mark.default_cassette("cargurus_one_page")
def test_cargurus_one_page() -> None:
    url = cg.build_search_url(1)
    session = cg.make_session()
    try:
        resp = session.get(url, timeout=cg.REQUEST_TIMEOUT, proxies={"http": "", "https": ""})
    except requests.RequestException as exc:  # pragma: no cover - network
        pytest.skip(f"cargurus request failed: {exc}")
    assert resp.status_code == 200
    rows = cg.parse_listings(resp.text)
    assert rows and rows[0]["source"] == "cargurus"
    assert "?" not in rows[0]["url"] and "#" not in rows[0]["url"]
    datetime.fromisoformat(rows[0]["first_seen"])
