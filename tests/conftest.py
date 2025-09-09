import sys
from pathlib import Path
import pytest

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests that hit live websites",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: mark test as requiring live HTTP")
    config.addinivalue_line(
        "markers", "vcr: record/replay HTTP requests using pytest-recording"
    )
    config.addinivalue_line(
        "markers", "default_cassette(name): set cassette name for pytest-recording"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="need --live option to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
