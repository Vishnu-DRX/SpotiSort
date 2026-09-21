import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SPOTISORT_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set SPOTISORT_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def load_fixture():
    def _load(name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load
