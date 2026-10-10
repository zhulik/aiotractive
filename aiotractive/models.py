"""Typed status models for the Tractive API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LATLONG_LENGTH = 2

SWITCH_EVENT_KEYS: dict[str, str] = {
    "buzzer_control": "buzzer",
    "led_control": "led",
    "live_tracking": "live_tracking",
}


@dataclass(slots=True)
class TrackerStatus:
    """Live status of one tracker, merged from REST and push events."""

    battery_level: int | None = None
    tracker_state: str | None = None
    battery_charging: bool | None = None
    power_saving: bool | None = None
    power_saving_zone: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy: float | None = None
    sensor_used: str | None = None
    buzzer: bool | None = None
    led: bool | None = None
    live_tracking: bool | None = None


@dataclass(slots=True)
class PetStatus:
    """Health overview of one pet."""

    daily_goal: int | None = None
    minutes_active: int | None = None
    minutes_day_sleep: int | None = None
    minutes_night_sleep: int | None = None
    minutes_rest: int | None = None


@dataclass(slots=True)
class TractiveStatus:
    """Status of every tracker and pet of the account."""

    trackers: dict[str, TrackerStatus] = field(default_factory=dict)
    pets: dict[str, PetStatus] = field(default_factory=dict)


@dataclass(slots=True)
class Trackable:
    """A pet together with the tracker assigned to it."""

    pet_id: str
    tracker_id: str
    pet_details: dict[str, Any]
    tracker_details: dict[str, Any]

    @property
    def name(self) -> str:
        """Return the name of the pet."""
        name: str = self.pet_details["details"]["name"]
        return name

    @property
    def weight(self) -> int | None:
        """Return the raw API weight of the pet in grams, or None if missing."""
        weight: int | None = self.pet_details["details"].get("weight")
        return weight


def update_tracker_hardware(status: TrackerStatus, event: dict[str, Any]) -> None:
    """Apply the hardware block of a tracker event to the status.

    Missing fields keep their last known value, except that an explicit tracker
    state without a reason clears power saving.
    """
    hw = event.get("hardware")
    if not hw:
        return
    if "battery_level" in hw:
        status.battery_level = hw["battery_level"]
    if (tracker_state := event.get("tracker_state")) is not None:
        status.tracker_state = tracker_state.lower()
    if "charging_state" in event:
        status.battery_charging = event["charging_state"] == "CHARGING"
    if tracker_state is not None or "tracker_state_reason" in event:
        status.power_saving = event.get("tracker_state_reason") == "POWER_SAVING"


def update_tracker_position(status: TrackerStatus, event: dict[str, Any]) -> None:
    """Apply the position block of a tracker event to the status.

    Only fields carried by the event are overwritten; missing keys keep the
    last known value.
    """
    pos = event.get("position")
    if not pos:
        return
    latlong = pos.get("latlong")
    if isinstance(latlong, list) and len(latlong) == LATLONG_LENGTH:
        status.latitude, status.longitude = latlong
    if "accuracy" in pos:
        status.accuracy = pos["accuracy"]
    if "sensor_used" in pos:
        status.sensor_used = pos["sensor_used"]


def update_tracker_switches(status: TrackerStatus, event: dict[str, Any]) -> None:
    """Apply switch (buzzer/LED/live tracking) and power saving zone data."""
    for event_key, status_key in SWITCH_EVENT_KEYS.items():
        switch_data = event.get(event_key)
        if switch_data is None:
            continue

        active = switch_data.get("active")
        # The API keeps reporting a timed out LED or buzzer as active, with no
        # time remaining
        if event_key != "live_tracking" and switch_data.get("remaining") == 0:
            active = False

        setattr(status, status_key, active)

    hw = event.get("hardware")
    if hw and "power_saving_zone_id" in hw:
        status.power_saving_zone = hw["power_saving_zone_id"] is not None


def update_pet_from_health_overview(status: PetStatus, data: dict[str, Any]) -> None:
    """Apply a health overview payload to the pet status.

    A missing key sets the field to ``None``: a health overview without sleep
    data means the sleep values are unknown.
    """
    activity = data.get("activity") or {}
    sleep = data.get("sleep") or {}
    status.daily_goal = activity.get("minutesGoal")
    status.minutes_active = activity.get("minutesActive")
    status.minutes_day_sleep = sleep.get("minutesDaySleep")
    status.minutes_night_sleep = sleep.get("minutesNightSleep")
    status.minutes_rest = sleep.get("minutesCalm")


def update_tracker_from_rest(
    status: TrackerStatus,
    details: dict[str, Any],
    hw_info: dict[str, Any],
    pos_report: dict[str, Any],
) -> None:
    """Apply REST payloads to the tracker status.

    Missing keys keep the last known value. Switch states (buzzer, LED, live
    tracking) are not available via REST.
    """
    if "battery_level" in hw_info:
        status.battery_level = hw_info["battery_level"]
    if (state := details.get("state")) is not None:
        status.tracker_state = state.lower()
    if "charging_state" in details:
        status.battery_charging = details["charging_state"] == "CHARGING"
    if "state_reason" in details:
        status.power_saving = details["state_reason"] == "POWER_SAVING"
    if "power_saving_zone_id" in hw_info:
        status.power_saving_zone = hw_info["power_saving_zone_id"] is not None
    latlong = pos_report.get("latlong")
    if isinstance(latlong, list) and len(latlong) == LATLONG_LENGTH:
        status.latitude, status.longitude = latlong
    if "pos_uncertainty" in pos_report:
        status.accuracy = pos_report["pos_uncertainty"]
    if "sensor_used" in pos_report:
        status.sensor_used = pos_report["sensor_used"]
