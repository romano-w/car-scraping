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
        help="run tests that hit the live network",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "live: mark test as requiring network access")


def pytest_runtest_setup(item: pytest.Item) -> None:
    if "live" in item.keywords and not item.config.getoption("--live"):
        pytest.skip("need --live option to run")
