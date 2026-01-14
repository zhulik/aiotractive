"""Shared pytest fixtures for aiotractive tests.

These fixtures are based on real anonymized API responses from the Tractive API.
Fixture data is stored in JSON files in the fixtures/ directory.
"""

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture from a JSON file."""
    with (FIXTURES_DIR / f"{name}.json").open(encoding="utf-8") as file:
        return json.load(file)  # type: ignore[no-any-return]


@pytest.fixture
def auth_response() -> dict[str, Any]:
    """Return standard authentication response."""
    return load_fixture("auth_response")
