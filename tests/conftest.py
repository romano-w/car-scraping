import sys
from pathlib import Path
import pytest

# Ensure project root is on sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run live network tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="use --live to run integration tests")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
