"""Tests for the Tracker class."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiotractive.tracker import Tracker

TRACKER_ID = "tracker_abc123"
TRACKER_DATA = {"_id": TRACKER_ID, "_type": "tracker"}


@pytest.fixture
def mock_api() -> MagicMock:
    """Create a mock API instance."""
    api = MagicMock()
    api.request = AsyncMock()
    return api


@pytest.fixture
def tracker(mock_api: MagicMock) -> Tracker:
    """Create a Tracker instance with a mocked API."""
    return Tracker(mock_api, TRACKER_DATA)


async def test_hw_info_returns_data(tracker: Tracker, mock_api: MagicMock) -> None:
    """Test that hw_info returns the response from the API."""
    expected: dict[str, Any] = {"battery_level": 85, "firmware_version": "1.2.3"}
    mock_api.request.return_value = expected

    result = await tracker.hw_info()

    mock_api.request.assert_awaited_once_with(f"device_hw_report/{TRACKER_ID}/")
    assert result == expected


async def test_hw_info_returns_empty_dict_when_api_returns_none(
    tracker: Tracker, mock_api: MagicMock
) -> None:
    """Test that hw_info returns {} when the API returns None."""
    mock_api.request.return_value = None

    result = await tracker.hw_info()

    mock_api.request.assert_awaited_once_with(f"device_hw_report/{TRACKER_ID}/")
    assert result == {}


async def test_hw_info_returns_empty_dict_when_api_returns_empty_dict(
    tracker: Tracker, mock_api: MagicMock
) -> None:
    """Test that hw_info returns {} when the API returns an empty dict."""
    mock_api.request.return_value = {}

    result = await tracker.hw_info()

    assert result == {}
