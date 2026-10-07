"""Tests for the TrackableObject class."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiotractive.api import API
from aiotractive.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    TractiveError,
    UnauthorizedError,
)
from aiotractive.trackable_object import TrackableObject

from .conftest import load_fixture

PET_ID = "pet_id_123"


@pytest.fixture
def mock_api() -> MagicMock:
    """Create a mock API instance."""
    api = MagicMock()
    api.request = AsyncMock()
    api.APS_API_URL = API.APS_API_URL
    return api


@pytest.fixture
def pet(mock_api: MagicMock) -> TrackableObject:
    """Create a TrackableObject instance with a mocked API."""
    return TrackableObject(mock_api, {"_id": PET_ID, "_type": "pet"})


async def test_health_overview_returns_data(
    pet: TrackableObject, mock_api: MagicMock
) -> None:
    """Test that health_overview returns the APS API response."""
    expected: dict[str, Any] = load_fixture("health_overview")
    mock_api.request.return_value = expected

    result = await pet.health_overview()

    mock_api.request.assert_awaited_once_with(
        f"pet/{PET_ID}/health/overview", base_url=API.APS_API_URL
    )
    assert result == expected


@pytest.mark.parametrize("error", [BadRequestError, ForbiddenError])
async def test_health_overview_unsupported_returns_empty(
    pet: TrackableObject, mock_api: MagicMock, error: type[TractiveError]
) -> None:
    """Test that a pet without health overview (400 or 403) yields an empty dict."""
    mock_api.request.side_effect = error()

    assert await pet.health_overview() == {}


@pytest.mark.parametrize("error", [UnauthorizedError, NotFoundError, TractiveError])
async def test_health_overview_propagates_other_errors(
    pet: TrackableObject, mock_api: MagicMock, error: type[TractiveError]
) -> None:
    """Test that other errors are not swallowed."""
    mock_api.request.side_effect = error()

    with pytest.raises(error):
        await pet.health_overview()
