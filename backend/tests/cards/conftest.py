import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(scope="session")
def rifthunt_sample() -> dict[str, Any]:
    """A slice of the real Rifthunt bulk snapshot: 32 printings of 8 distinct cards."""
    return json.loads((FIXTURES / "rifthunt_sample.json").read_text(encoding="utf-8"))
