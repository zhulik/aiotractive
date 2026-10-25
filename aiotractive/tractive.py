"""Entrypoint for the Tractive REST API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from functools import partial
from types import TracebackType
from typing import Any, Self

from .api import API
from .channel import Channel
from .exceptions import TractiveError, UnauthorizedError
from .models import (
    PetStatus,
    Trackable,
    TrackerStatus,
    TractiveStatus,
    update_pet_from_health_overview,
    update_tracker_from_rest,
    update_tracker_hardware,
    update_tracker_position,
    update_tracker_state,
    update_tracker_switches,
)
from .trackable_object import TrackableObject
from .tracker import Tracker

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 10
PET_DETAILS_REFRESH_INTERVAL = 30 * 60  # seconds


def _is_new(cache: dict[str, float], tracker_id: str, timestamp: float | None) -> bool:
    """Return whether the timestamp is new for the tracker, and remember it."""
    if timestamp is None or cache.get(tracker_id) == timestamp:
        return False
    cache[tracker_id] = timestamp
    return True


class Tractive:
    """Asynchronous Python client for the Tractive REST API."""

    def __init__(
        self,
        *args: Any,  # noqa: ANN401
        fetch_delay: float = 2.0,
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        """Initialize the client."""
        self._api = API(*args, **kwargs)
        self._fetch_delay = fetch_delay
        self.status: TractiveStatus = TractiveStatus()
        self._trackables: list[Trackable] | None = None
        self._details_fresh = False
        self._pet_details_fetched: float | None = None
        self._last_hw_time: dict[str, float] = {}
        self._last_pos_time: dict[str, float] = {}
        self._update_listener: Callable[[Exception | None], None] | None = None

    def subscribe_updates(
        self, update_listener: Callable[[Exception | None], None]
    ) -> None:
        """Register a callback for push updates."""
        self._update_listener = update_listener

    def _notify(self, exc: Exception | None) -> None:
        """Call the update listener, logging (not propagating) its errors."""
        if self._update_listener is None:
            return
        try:
            self._update_listener(exc)
        except Exception:  # a listener bug must not stop the loop
            _LOGGER.exception("Error in update listener")

    async def listen(self) -> None:
        """Consume real-time events and keep ``status`` up to date."""
        tasks = {
            asyncio.create_task(self._listen_channel()),
            asyncio.create_task(self._refresh_pet_details_periodically()),
        }
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            # wait() never raises task errors, so every task is awaited.
            await asyncio.wait(tasks)

    async def _listen_channel(self) -> None:
        """Consume channel events until an ``UnauthorizedError``."""
        while True:
            self._last_hw_time.clear()
            self._last_pos_time.clear()
            try:
                channel = Channel(self._api, on_connected=partial(self._notify, None))
                async with contextlib.aclosing(channel.listen()) as events:
                    async for event in events:
                        try:
                            self._update_status(event)
                        except (KeyError, TypeError, AttributeError, ValueError) as err:
                            # The event may contain the pet position; log it
                            # only at debug level.
                            _LOGGER.warning("Ignoring malformed event: %s", err)
                            _LOGGER.debug("Malformed event: %s", event)
                            continue
                        self._notify(None)
            except UnauthorizedError as exc:
                self._notify(exc)
                return
            except Exception as exc:  # noqa: BLE001 - any other error is transient, reconnect
                self._notify(exc)
                await asyncio.sleep(RECONNECT_INTERVAL)

    async def _refresh_pet_details_periodically(self) -> None:
        """Refresh the pet details every interval until an ``UnauthorizedError``."""
        started = time.monotonic()
        while True:
            last = max(started, self._pet_details_fetched or started)
            delay = last + PET_DETAILS_REFRESH_INTERVAL - time.monotonic()
            if delay > 0:
                # Re-check after waking: a manual fetch may have moved the due time.
                await asyncio.sleep(delay)
                continue
            # A failed attempt also counts, so errors do not cause a retry storm.
            self._pet_details_fetched = time.monotonic()
            try:
                await self.async_refresh_pet_details()
            except UnauthorizedError as exc:
                self._notify(exc)
                return
            except TractiveError as err:
                _LOGGER.warning("Failed to refresh pet details: %s", err)
                # A pet may have been removed; re-fetch the trackables next time.
                self._trackables = None
            except Exception:  # keep the channel alive, retry next interval
                _LOGGER.exception("Failed to refresh pet details")
            else:
                self._notify(None)

    def _update_status(self, event: dict[str, Any]) -> None:
        """Update the status from an event."""
        if event.get("message") == "health_overview":
            data = event.get("content", event)
            pet_id = data.get("petId")
            if pet_id is None:
                return
            _LOGGER.debug("Health overview event for pet %s: %s", pet_id, data)
            update_pet_from_health_overview(
                self.status.pets.setdefault(pet_id, PetStatus()), data
            )
            for trackable in self._trackables or []:
                if trackable.pet_id == pet_id:
                    trackable.health_available = True
                    break
            return

        tracker_id = event.get("tracker_id")
        if tracker_id is None:
            _LOGGER.debug("Ignoring event %s", event.get("message"))
            return
        _LOGGER.debug(
            "Event %s for tracker %s: %s", event.get("message"), tracker_id, event
        )
        status = self.status.trackers.setdefault(tracker_id, TrackerStatus())

        # State changes can arrive without a new hardware sample.
        update_tracker_state(status, event)
        hw_time = (event.get("hardware") or {}).get("time")
        if _is_new(self._last_hw_time, tracker_id, hw_time):
            update_tracker_hardware(status, event)
        pos_time = (event.get("position") or {}).get("time")
        if _is_new(self._last_pos_time, tracker_id, pos_time):
            update_tracker_position(status, event)
        update_tracker_switches(status, event)

    def _apply_pet_details(self, trackable: Trackable) -> None:
        """Copy the pet weight from the cached details to the status."""
        self.status.pets.setdefault(
            trackable.pet_id, PetStatus()
        ).weight = trackable.weight

    async def async_fetch_trackables(self) -> list[Trackable]:
        """Fetch the pets that have a tracker assigned, with their details."""
        trackables: list[Trackable] = []
        for index, obj in enumerate(await self.trackable_objects()):
            if index and self._fetch_delay:
                await asyncio.sleep(self._fetch_delay)
            data = await obj.details()
            if not (device_id := data.get("device_id")):
                _LOGGER.info(
                    "Trackable object %s has no tracker assigned and will be skipped",
                    data.get("_id"),
                )
                continue
            if not data.get("details"):
                _LOGGER.info(
                    "Tracker %s has no details and will be skipped. "
                    "This happens for shared trackers",
                    device_id,
                )
                continue
            tracker_details = await self.tracker(device_id).details()
            if not tracker_details.get("_id"):
                msg = f"Tractive API returns incomplete data for tracker {device_id}"
                raise TractiveError(msg)
            trackable = Trackable(
                pet_id=data["_id"],
                tracker_id=device_id,
                pet_details=data,
                tracker_details=tracker_details,
            )
            trackables.append(trackable)
            self._apply_pet_details(trackable)
        self._trackables = trackables
        self._details_fresh = True
        self._pet_details_fetched = time.monotonic()
        return trackables

    async def async_fetch_status(self) -> TractiveStatus:
        """Refresh ``status`` of every trackable via REST."""
        if self._trackables is None:
            await self.async_fetch_trackables()
            if self._fetch_delay:
                await asyncio.sleep(self._fetch_delay)
        reuse_details, self._details_fresh = self._details_fresh, False
        for index, trackable in enumerate(self._trackables or []):
            if index and self._fetch_delay:
                await asyncio.sleep(self._fetch_delay)
            tracker = self.tracker(trackable.tracker_id)
            if reuse_details:
                tracker_details = trackable.tracker_details
            else:
                tracker_details = await tracker.details()
                trackable.tracker_details = tracker_details
            hw_info = await tracker.hw_info()
            pos_report = await tracker.pos_report()
            health = await self.trackable_object(trackable.pet_id).health_overview()
            trackable.health_available = health is not None
            update_tracker_from_rest(
                self.status.trackers.setdefault(trackable.tracker_id, TrackerStatus()),
                tracker_details,
                hw_info,
                pos_report,
            )
            if health:
                update_pet_from_health_overview(
                    self.status.pets.setdefault(trackable.pet_id, PetStatus()), health
                )
        return self.status

    async def async_refresh_pet_details(self) -> TractiveStatus:
        """Refresh the cached pet details and the pet weight via REST."""
        if self._trackables is None:
            await self.async_fetch_trackables()
            return self.status
        for index, trackable in enumerate(self._trackables):
            if index and self._fetch_delay:
                await asyncio.sleep(self._fetch_delay)
            data = await self.trackable_object(trackable.pet_id).details()
            if not isinstance(data, dict) or not isinstance(data.get("details"), dict):
                msg = f"Tractive API returns incomplete data for pet {trackable.pet_id}"
                raise TractiveError(msg)
            trackable.pet_details = data
            self._apply_pet_details(trackable)
        self._pet_details_fetched = time.monotonic()
        return self.status

    def tracker(self, tracker_id: str) -> Tracker:
        """Get tracker by ID."""
        return Tracker(
            self._api,
            tracker_id,
            status=self.status.trackers.setdefault(tracker_id, TrackerStatus()),
        )

    def trackable_object(self, trackable_id: str) -> TrackableObject:
        """Get trackable object by ID."""
        return TrackableObject(self._api, trackable_id)

    async def trackable_objects(self) -> list[TrackableObject]:
        """Get all trackable objects for the authenticated user."""
        trackable_objects: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackable_objects"
        )
        return [TrackableObject(self._api, t["_id"]) for t in trackable_objects]

    async def close(self) -> None:
        """Close open client session."""
        await self._api.close()

    async def __aenter__(self) -> Self:
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
