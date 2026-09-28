"""Tests for the Tracker class."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiotractive.models import TrackerStatus
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


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("hw_info", f"device_hw_report/{TRACKER_ID}/"),
        ("pos_report", f"device_pos_report/{TRACKER_ID}"),
    ],
)
async def test_report_returns_empty_dict_when_api_returns_none(
    tracker: Tracker, mock_api: MagicMock, method: str, url: str
) -> None:
    """Test that hw_info and pos_report return {} when the API returns None."""
    mock_api.request.return_value = None

    result = await getattr(tracker, method)()

    mock_api.request.assert_awaited_once_with(url)
    assert result == {}


async def test_hw_info_returns_empty_dict_when_api_returns_empty_dict(
    tracker: Tracker, mock_api: MagicMock
) -> None:
    """Test that hw_info returns {} when the API returns an empty dict."""
    mock_api.request.return_value = {}

    result = await tracker.hw_info()

    assert result == {}


@pytest.mark.parametrize(
    ("method", "command", "field"),
    [
        ("set_buzzer_active", "buzzer_control", "buzzer"),
        ("set_led_active", "led_control", "led"),
        ("set_live_tracking_active", "live_tracking", "live_tracking"),
    ],
)
@pytest.mark.parametrize(
    ("active", "action", "response", "expected"),
    [
        (True, "on", {"pending": True}, True),
        (False, "off", {"pending": True}, False),
        (True, "on", {"pending": False}, False),
        (False, "off", {"pending": False}, True),
        (True, "on", {}, False),
        (False, "off", {}, True),
    ],
)
async def test_set_switch_updates_bound_status(
    mock_api: MagicMock,
    method: str,
    command: str,
    field: str,
    active: bool,
    action: str,
    response: dict[str, Any],
    expected: bool,
) -> None:
    """Test that only a pending switch command updates the bound status."""
    status = TrackerStatus()
    setattr(status, field, not active)
    tracker = Tracker(mock_api, TRACKER_DATA, status)
    mock_api.request.return_value = response

    result = await getattr(tracker, method)(active)

    mock_api.request.assert_awaited_once_with(
        f"tracker/{TRACKER_ID}/command/{command}/{action}"
    )
    assert result is response
    assert getattr(status, field) is expected


@pytest.mark.parametrize(
    "method", ["set_buzzer_active", "set_led_active", "set_live_tracking_active"]
)
async def test_set_switch_without_bound_status(
    tracker: Tracker, mock_api: MagicMock, method: str
) -> None:
    """Test that switch commands work when no status is bound."""
    response: dict[str, Any] = {"pending": True}
    mock_api.request.return_value = response

    result = await getattr(tracker, method)(True)  # noqa: FBT003

    assert result is response
