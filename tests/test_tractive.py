"""Tests for the Tractive client status handling."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from aiotractive import Tractive

TRACKER_ID = "tracker_abc123"


@pytest.fixture
def client() -> Tractive:
    """Create a Tractive client with a known tracker status."""
    tractive = Tractive("test@example.com", "password", session=MagicMock())
    tractive.status["trackers"][TRACKER_ID] = {"tracker_state": "operational"}
    return tractive


@pytest.mark.parametrize(
    ("event", "expected_state"),
    [
        (
            {
                "tracker_id": TRACKER_ID,
                "hardware": {"time": 1, "battery_level": 80},
                "position": {},
                "tracker_state": "NOT_REPORTING",
            },
            "not_reporting",
        ),
        (
            {
                "tracker_id": TRACKER_ID,
                "hardware": {"time": 1, "battery_level": 80},
                "position": {},
            },
            "operational",
        ),
    ],
)
def test_update_status_tracker_state(
    client: Tractive, event: dict[str, Any], expected_state: str
) -> None:
    """Test that a hardware event without tracker_state keeps the last known state."""
    client._last_hw_time = 0
    client._last_pos_time = 0

    client._update_status(event)

    tracker_status = client.status["trackers"][TRACKER_ID]
    assert tracker_status["tracker_state"] == expected_state
    assert tracker_status["battery_level"] == 80
