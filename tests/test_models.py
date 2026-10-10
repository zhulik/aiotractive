"""Tests for the typed status models."""

from __future__ import annotations

from typing import Any

import pytest

from aiotractive.models import (
    PetStatus,
    Trackable,
    TrackerStatus,
    TractiveStatus,
    update_pet_from_health_overview,
    update_tracker_from_rest,
    update_tracker_hardware,
    update_tracker_position,
    update_tracker_switches,
)

from .conftest import load_fixture

FULL_HW_EVENT: dict[str, Any] = {
    "hardware": {"battery_level": 42},
    "tracker_state": "OPERATIONAL",
    "charging_state": "CHARGING",
    "tracker_state_reason": "POWER_SAVING",
}


def _previous() -> TrackerStatus:
    """Return a fully populated status to detect unwanted overwrites."""
    return TrackerStatus(
        battery_level=10,
        tracker_state="previous",
        battery_charging=False,
        power_saving=False,
        power_saving_zone=False,
        latitude=1.0,
        longitude=2.0,
        accuracy=3.0,
        sensor_used="GPS",
        buzzer=False,
        led=False,
        live_tracking=False,
    )


def test_update_tracker_hardware_full_event() -> None:
    """Test that a full hardware event sets every hardware field."""
    status = _previous()

    update_tracker_hardware(status, FULL_HW_EVENT)

    assert status.battery_level == 42
    assert status.tracker_state == "operational"
    assert status.battery_charging is True
    assert status.power_saving is True


@pytest.mark.parametrize(
    ("event", "field", "expected"),
    [
        (
            {"hardware": {"other": 1}, "charging_state": "CHARGING"},
            "battery_level",
            10,
        ),
        ({"hardware": {"battery_level": 5}}, "tracker_state", "previous"),
        ({"hardware": {"battery_level": 5}}, "battery_charging", False),
        ({"hardware": {"battery_level": 5}}, "power_saving", False),
        (
            {"hardware": {"battery_level": 5}, "tracker_state": None},
            "tracker_state",
            "previous",
        ),
    ],
)
def test_update_tracker_hardware_partial_event(
    event: dict[str, Any], field: str, expected: object
) -> None:
    """Test that missing keys keep the previous value."""
    status = _previous()

    update_tracker_hardware(status, event)

    assert getattr(status, field) == expected


@pytest.mark.parametrize(
    ("event", "field"),
    [
        (
            {"hardware": {"battery_level": 5}, "charging_state": "NOT_CHARGING"},
            "battery_charging",
        ),
        (
            {"hardware": {"battery_level": 5}, "tracker_state_reason": "OTHER"},
            "power_saving",
        ),
    ],
)
def test_update_tracker_hardware_clears_flag(event: dict[str, Any], field: str) -> None:
    """Test that a non-matching charging state or reason sets the flag to False."""
    status = _previous()
    setattr(status, field, True)

    update_tracker_hardware(status, event)

    assert getattr(status, field) is False


@pytest.mark.parametrize(
    "event",
    [
        {k: v for k, v in FULL_HW_EVENT.items() if k != "hardware"},
        {**FULL_HW_EVENT, "hardware": None},
        {**FULL_HW_EVENT, "hardware": {}},
    ],
)
def test_update_tracker_hardware_without_hardware(event: dict[str, Any]) -> None:
    """Test that a missing or empty hardware block leaves the status untouched."""
    status = _previous()

    update_tracker_hardware(status, event)

    assert status == _previous()


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"tracker_state": "OPERATIONAL"}, False),
        ({"tracker_state": "NOT_REPORTING"}, False),
        ({"tracker_state_reason": "POWER_SAVING"}, True),
        ({"tracker_state_reason": "OTHER"}, False),
        ({"tracker_state_reason": None}, False),
        ({}, True),
        ({"tracker_state": None}, True),
    ],
)
def test_update_tracker_hardware_power_saving(
    fields: dict[str, Any], expected: bool
) -> None:
    """Test state snapshots clear absent reasons, but partial events preserve them."""
    status = TrackerStatus(tracker_state="operational", power_saving=True)

    update_tracker_hardware(status, {"hardware": {"battery_level": 42}, **fields})

    assert status.power_saving is expected


def test_update_tracker_position_full_event() -> None:
    """Test that a full position event sets every position field."""
    status = _previous()

    update_tracker_position(
        status,
        {
            "position": {
                "latlong": [50.5, 19.5],
                "accuracy": 12,
                "sensor_used": "KNOWN_WIFI",
            }
        },
    )

    assert status.latitude == 50.5
    assert status.longitude == 19.5
    assert status.accuracy == 12
    assert status.sensor_used == "KNOWN_WIFI"


@pytest.mark.parametrize(
    "position",
    [
        {"accuracy": 12},
        {"latlong": None, "accuracy": 12},
        {"latlong": [50.5], "accuracy": 12},
        {"latlong": [50.5, 19.5, 7.0], "accuracy": 12},
    ],
)
def test_update_tracker_position_invalid_latlong(position: dict[str, Any]) -> None:
    """Test that a missing or malformed latlong keeps the previous coordinates."""
    status = _previous()

    update_tracker_position(status, {"position": position})

    assert status.latitude == 1.0
    assert status.longitude == 2.0
    assert status.accuracy == 12


@pytest.mark.parametrize(
    ("position", "accuracy", "sensor_used"),
    [
        ({"latlong": [50.5, 19.5]}, 3.0, "GPS"),
        ({"latlong": [50.5, 19.5], "accuracy": 12}, 12, "GPS"),
        ({"latlong": [50.5, 19.5], "sensor_used": "KNOWN_WIFI"}, 3.0, "KNOWN_WIFI"),
    ],
)
def test_update_tracker_position_optional_fields(
    position: dict[str, Any], accuracy: float, sensor_used: str
) -> None:
    """Test that accuracy and sensor_used are only set when present."""
    status = _previous()

    update_tracker_position(status, {"position": position})

    assert status.accuracy == accuracy
    assert status.sensor_used == sensor_used


@pytest.mark.parametrize("event", [{}, {"position": None}, {"position": {}}])
def test_update_tracker_position_without_position(event: dict[str, Any]) -> None:
    """Test that a missing or empty position block leaves the status untouched."""
    status = _previous()

    update_tracker_position(status, event)

    assert status == _previous()


@pytest.mark.parametrize(
    ("event_key", "field", "active"),
    [
        ("buzzer_control", "buzzer", True),
        ("buzzer_control", "buzzer", False),
        ("led_control", "led", True),
        ("led_control", "led", False),
        ("live_tracking", "live_tracking", True),
        ("live_tracking", "live_tracking", False),
    ],
)
def test_update_tracker_switches(
    event_key: str,
    field: str,
    active: bool,
) -> None:
    """Test that each switch event sets only its own field."""
    status = TrackerStatus()

    update_tracker_switches(status, {event_key: {"active": active}})

    expected = TrackerStatus()
    setattr(expected, field, active)
    assert status == expected


@pytest.mark.parametrize(
    ("event_key", "field", "expired"),
    [
        ("buzzer_control", "buzzer", False),
        ("led_control", "led", False),
        ("live_tracking", "live_tracking", True),
    ],
)
def test_update_tracker_switches_timed_switch_expired(
    event_key: str,
    field: str,
    expired: bool,
) -> None:
    """Test that a timed out LED or buzzer is off; live tracking is not timed."""
    status = TrackerStatus()

    update_tracker_switches(
        status, {event_key: {"active": True, "timeout": 900, "remaining": 896}}
    )
    assert getattr(status, field) is True

    update_tracker_switches(
        status, {event_key: {"active": True, "timeout": 900, "remaining": 0}}
    )
    assert getattr(status, field) is expired


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"hardware": {"power_saving_zone_id": "zone"}}, True),
        ({"hardware": {"power_saving_zone_id": None}}, False),
        ({"hardware": {"battery_level": 5}}, None),
        ({"hardware": None}, None),
        ({}, None),
    ],
)
def test_update_tracker_switches_power_saving_zone(
    event: dict[str, Any],
    expected: bool | None,
) -> None:
    """Test power saving zone derivation from the hardware block."""
    status = TrackerStatus()

    update_tracker_switches(status, event)

    assert status.power_saving_zone is expected


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (load_fixture("health_overview"), PetStatus(200, 150, 100, 300, 122)),
        (
            {"activity": {"minutesGoal": 200, "minutesActive": 150}},
            PetStatus(200, 150, None, None, None),
        ),
        (
            {
                "sleep": {
                    "minutesDaySleep": 100,
                    "minutesNightSleep": 300,
                    "minutesCalm": 122,
                }
            },
            PetStatus(None, None, 100, 300, 122),
        ),
        ({"activity": None, "sleep": None}, PetStatus()),
    ],
)
def test_update_pet_from_health_overview(
    data: dict[str, Any], expected: PetStatus
) -> None:
    """Test that missing blocks reset the corresponding fields to None."""
    status = PetStatus(1, 2, 3, 4, 5)

    update_pet_from_health_overview(status, data)

    assert status == expected


def test_update_tracker_from_rest_fixtures() -> None:
    """Test applying real REST payloads; switch states keep their value."""
    status = _previous()

    update_tracker_from_rest(
        status,
        load_fixture("tracker_details"),
        load_fixture("tracker_hw_info"),
        load_fixture("tracker_pos_report"),
    )

    assert status == TrackerStatus(
        battery_level=96,
        tracker_state="operational",
        battery_charging=False,
        power_saving=True,
        power_saving_zone=True,
        latitude=33.222222,
        longitude=44.555555,
        accuracy=30,
        sensor_used="KNOWN_WIFI",
        buzzer=False,
        led=False,
        live_tracking=False,
    )


def test_update_tracker_from_rest_empty() -> None:
    """Test that empty REST payloads keep every previous value."""
    status = _previous()

    update_tracker_from_rest(status, {}, {}, {})

    assert status == _previous()


@pytest.mark.parametrize(
    ("details", "hw_info", "field", "expected"),
    [
        ({"charging_state": "CHARGING"}, {}, "battery_charging", True),
        ({"state_reason": "OTHER"}, {}, "power_saving", False),
        ({}, {"power_saving_zone_id": None}, "power_saving_zone", False),
    ],
)
def test_update_tracker_from_rest_flags(
    details: dict[str, Any],
    hw_info: dict[str, Any],
    field: str,
    expected: bool,
) -> None:
    """Test derivation of boolean flags from REST payloads."""
    status = TrackerStatus()

    update_tracker_from_rest(status, details, hw_info, {})

    assert getattr(status, field) is expected


def test_trackable_name() -> None:
    """Test that the trackable name comes from the pet details."""
    trackable = Trackable(
        pet_id="pet_id_123",
        tracker_id="device_id_123",
        pet_details=load_fixture("trackable_object"),
        tracker_details=load_fixture("tracker_details"),
    )

    assert trackable.name == "Test Pet"


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (23700, 23700),
        (None, None),
        ("missing", None),
    ],
)
def test_trackable_weight(weight: object, expected: int | None) -> None:
    """Test that the trackable weight comes from the pet details."""
    pet_details = load_fixture("trackable_object")
    if weight == "missing":
        del pet_details["details"]["weight"]
    else:
        pet_details["details"]["weight"] = weight
    trackable = Trackable(
        pet_id="pet_id_123",
        tracker_id="device_id_123",
        pet_details=pet_details,
        tracker_details=load_fixture("tracker_details"),
    )

    assert trackable.weight == expected


def test_tractive_status_defaults_are_independent() -> None:
    """Test that default containers are not shared between instances."""
    first = TractiveStatus()
    second = TractiveStatus()

    first.trackers["tracker"] = TrackerStatus()
    first.pets["pet"] = PetStatus()

    assert first.trackers is not second.trackers
    assert second.trackers == {}
    assert second.pets == {}
