"""Entrypoint for the Tractive REST API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from types import TracebackType
from typing import Any

from .api import API
from .channel import Channel
from .exceptions import DisconnectedError, TractiveError, UnauthorizedError
from .trackable_object import TrackableObject
from .tracker import Tracker

RECONNECT_INTERVAL = 10

SWITCH_EVENT_KEYS: dict[str, str] = {
    "buzzer_control": "buzzer",
    "led_control": "led",
    "live_tracking": "live_tracking",
}


class Tractive:
    """Asynchronous Python client for the Tractive REST API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the client."""
        self._api = API(*args, **kwargs)
        self.status: dict[str, dict[str, Any]] = {
            "trackers": {},
            "pets": {},
        }
        self._update_listener: Callable[
            [Exception | None], None
        ] | None = None
        self._background_task: asyncio.Task[None] | None = None

    def subscribe_updates(
        self, update_listener: Callable[[Exception | None], None]
    ) -> None:
        """Register a callback for push updates.

        The callback will be called whenever new event data arrives.
        The argument is None on successful update, or an Exception on error.
        """
        self._update_listener = update_listener

    async def async_start_listener(self) -> None:
        """Start the background listener for real-time events."""
        if self._background_task is not None:
            return
        self._background_task = asyncio.create_task(
            self._async_background_listener()
        )

    async def async_stop_listener(self) -> None:
        """Stop the background listener."""
        if self._background_task is None:
            return
        self._background_task.cancel()
        try:
            await self._background_task
        except asyncio.CancelledError:
            pass
        self._background_task = None

    async def _async_background_listener(self) -> None:
        """Background task to consume events and update status."""
        self._last_hw_time: float = 0
        self._last_pos_time: float = 0

        while True:
            try:
                async for event in Channel(self._api).listen():
                    self._update_status(event)
                    if self._update_listener:
                        self._update_listener(None)
            except UnauthorizedError as exc:
                if self._update_listener:
                    self._update_listener(exc)
                return
            except (TractiveError, DisconnectedError) as exc:
                self._last_hw_time = 0
                self._last_pos_time = 0
                if self._update_listener:
                    self._update_listener(exc)
                await asyncio.sleep(RECONNECT_INTERVAL)
                continue
            except asyncio.CancelledError:
                return
            except Exception as exc:
                if self._update_listener:
                    self._update_listener(exc)
                await asyncio.sleep(RECONNECT_INTERVAL)
                continue

    def _update_status(self, event: dict[str, Any]) -> None:
        """Update the status dict from an event."""
        if event.get("message") == "health_overview":
            data = event.get("content", event)
            pet_id = data.get("petId")
            if pet_id is None:
                return
            self.status["pets"].setdefault(pet_id, {})
            activity = data.get("activity") or {}
            sleep = data.get("sleep") or {}
            self.status["pets"][pet_id].update(
                {
                    "daily_goal": activity.get("minutesGoal"),
                    "minutes_active": activity.get("minutesActive"),
                    "minutes_day_sleep": sleep.get("minutesDaySleep"),
                    "minutes_night_sleep": sleep.get("minutesNightSleep"),
                    "minutes_rest": sleep.get("minutesCalm"),
                }
            )
            return

        tracker_id = event.get("tracker_id")
        if tracker_id is None:
            return

        self.status["trackers"].setdefault(tracker_id, {})

        if (hw_time := event["hardware"].get("time")) is not None and self._last_hw_time != hw_time:
            self._last_hw_time = hw_time
            hw = event["hardware"]
            self.status["trackers"][tracker_id].update(
                {
                    "battery_level": hw.get("battery_level"),
                    "tracker_state": event.get("tracker_state", "").lower(),
                    "power_saving": event.get("tracker_state_reason") == "POWER_SAVING",
                    "battery_charging": event.get("charging_state") == "CHARGING",
                }
            )

        if (pos_time := event["position"].get("time")) is not None and self._last_pos_time != pos_time:
            self._last_pos_time = pos_time
            pos = event["position"]
            latlong = pos.get("latlong", [None, None])
            self.status["trackers"][tracker_id].update(
                {
                    "latitude": latlong[0],
                    "longitude": latlong[1],
                    "accuracy": pos.get("accuracy"),
                    "sensor_used": pos.get("sensor_used"),
                }
            )

        for event_key, status_key in SWITCH_EVENT_KEYS.items():
            switch_data = event.get(event_key)
            if switch_data is not None:
                self.status["trackers"][tracker_id][status_key] = switch_data.get(
                    "active"
                )

        hw_data = event.get("hardware", {})
        if "power_saving_zone_id" in hw_data:
            self.status["trackers"][tracker_id]["power_saving"] = (
                hw_data.get("power_saving_zone_id") is not None
            )

    async def authenticate(self) -> dict[str, Any] | None:
        """Authenticate the client."""
        return await self._api.authenticate()

    async def trackers(self) -> list[Tracker]:
        """Get all trackers for the authenticated user."""
        trackers_list: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackers"
        )
        return [Tracker(self._api, t) for t in trackers_list]

    def tracker(self, tracker_id: str) -> Tracker:
        """Get tracker by ID."""
        return Tracker(self._api, {"_id": tracker_id, "_type": "tracker"})

    def trackable_object(self, trackable_id: str) -> TrackableObject:
        """Get trackable object by ID."""
        return TrackableObject(self._api, {"_id": trackable_id, "_type": "pet"})

    async def trackable_objects(self) -> list[TrackableObject]:
        """Get all trackable objects for the authenticated user."""
        trackable_objects_list: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackable_objects"
        )
        return [TrackableObject(self._api, t) for t in trackable_objects_list]

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Listen for real-time events from the Tractive API."""
        async for event in Channel(self._api).listen():
            yield event

    async def close(self) -> None:
        """Close open client session."""
        await self.async_stop_listener()
        await self._api.close()

    async def __aenter__(self) -> Tractive:  # noqa: PYI034
        """Async enter."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async exit."""
        await self.close()
