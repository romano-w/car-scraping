import os
import pytest
import requests

os.environ.setdefault("CRAIGS_DOMAIN", "philadelphia")
import scrape_craigslist as cl


@pytest.mark.live
@pytest.mark.vcr
@pytest.mark.default_cassette("craigslist_one_page")
def test_craigslist_one_page() -> None:
    url = cl.build_search_url(1)
    session = cl.make_session()
    try:
        resp = session.get(url, timeout=cl.REQUEST_TIMEOUT, proxies={"http": "", "https": ""})
    except requests.RequestException as exc:  # pragma: no cover - network
        pytest.skip(f"craigslist request failed: {exc}")
    assert resp.status_code == 200
    rows = cl.parse_listings(resp.text)
    assert rows and rows[0]["source"] == "craigslist"
