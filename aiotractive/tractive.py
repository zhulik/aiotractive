"""Entrypoint for the Tractive REST API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from functools import partial
from types import TracebackType
from typing import Any

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
    update_tracker_switches,
)
from .trackable_object import TrackableObject
from .tracker import Tracker

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL = 10


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
        """Initialize the client.

        ``fetch_delay`` is the pause in seconds between the REST requests of
        consecutive trackables, to avoid HTTP 429 responses.
        """
        self._api = API(*args, **kwargs)
        self._fetch_delay = fetch_delay
        self.status: TractiveStatus = TractiveStatus()
        self._trackables: list[Trackable] | None = None
        self._details_fresh = False
        self._last_hw_time: dict[str, float] = {}
        self._last_pos_time: dict[str, float] = {}
        self._update_listener: Callable[[Exception | None], None] | None = None
        self._background_task: asyncio.Task[None] | None = None

    def subscribe_updates(
        self, update_listener: Callable[[Exception | None], None]
    ) -> None:
        """Register a callback for push updates.

        The argument is None when the status changed or the channel
        (re)connected, or an Exception when the channel failed.
        """
        self._update_listener = update_listener

    def _notify(self, exc: Exception | None) -> None:
        """Call the update listener, logging (not propagating) its errors."""
        if self._update_listener is None:
            return
        try:
            self._update_listener(exc)
        except Exception:  # a listener bug must not stop the loop
            _LOGGER.exception("Error in update listener")

    async def async_start_listener(self) -> None:
        """Start the background listener for real-time events."""
        if self._background_task is not None and not self._background_task.done():
            return
        self._background_task = asyncio.create_task(self.listen())

    async def async_stop_listener(self) -> None:
        """Stop the background listener."""
        if self._background_task is None:
            return
        self._background_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._background_task
        self._background_task = None

    async def listen(self) -> None:
        """Consume real-time events and keep ``status`` up to date.

        Runs until cancelled. Transient channel errors are reported to the
        listener and the channel reconnects after ``RECONNECT_INTERVAL``
        seconds; ``UnauthorizedError`` is reported and ends the loop.
        """
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

    def _update_status(self, event: dict[str, Any]) -> None:
        """Update the status from an event."""
        if event.get("message") == "health_overview":
            data = event.get("content", event)
            pet_id = data.get("petId")
            if pet_id is None:
                return
            update_pet_from_health_overview(
                self.status.pets.setdefault(pet_id, PetStatus()), data
            )
            return

        tracker_id = event.get("tracker_id")
        if tracker_id is None:
            return
        status = self.status.trackers.setdefault(tracker_id, TrackerStatus())

        hw_time = (event.get("hardware") or {}).get("time")
        if _is_new(self._last_hw_time, tracker_id, hw_time):
            update_tracker_hardware(status, event)
        pos_time = (event.get("position") or {}).get("time")
        if _is_new(self._last_pos_time, tracker_id, pos_time):
            update_tracker_position(status, event)
        update_tracker_switches(status, event)

    async def async_fetch_trackables(self) -> list[Trackable]:
        """Fetch the pets that have a tracker assigned, with their details.

        Requests are sequential with ``fetch_delay`` seconds between
        trackables. The result is cached for ``async_fetch_status``; the first
        ``async_fetch_status`` after this call reuses the fetched tracker details.
        """
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
            trackables.append(
                Trackable(
                    pet_id=data["_id"],
                    tracker_id=device_id,
                    pet_details=data,
                    tracker_details=tracker_details,
                )
            )
        self._trackables = trackables
        self._details_fresh = True
        return trackables

    async def async_fetch_status(self) -> TractiveStatus:
        """Refresh ``status`` of every trackable via REST.

        Per trackable, fresh tracker details, hardware info, position report
        and health overview are requested sequentially, with ``fetch_delay``
        seconds between trackables; the cached tracker details are refreshed.
        Fields not provided by REST (switch states) keep their last value.
        Tracker details fetched by a preceding ``async_fetch_trackables`` are
        reused once.
        """
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

    async def authenticate(self) -> dict[str, Any] | None:
        """Authenticate the client."""
        return await self._api.authenticate()

    async def trackers(self) -> list[Tracker]:
        """Get all trackers for the authenticated user."""
        trackers: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackers"
        )
        return [
            Tracker(
                self._api,
                t,
                status=self.status.trackers.setdefault(t["_id"], TrackerStatus()),
            )
            for t in trackers
        ]

    def tracker(self, tracker_id: str) -> Tracker:
        """Get tracker by ID."""
        return Tracker(
            self._api,
            {"_id": tracker_id, "_type": "tracker"},
            status=self.status.trackers.setdefault(tracker_id, TrackerStatus()),
        )

    def trackable_object(self, trackable_id: str) -> TrackableObject:
        """Get trackable object by ID."""
        return TrackableObject(self._api, {"_id": trackable_id, "_type": "pet"})

    async def trackable_objects(self) -> list[TrackableObject]:
        """Get all trackable objects for the authenticated user."""
        trackable_objects: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackable_objects"
        )
        return [TrackableObject(self._api, t) for t in trackable_objects]

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Listen for real-time events from the Tractive API."""
        async with contextlib.aclosing(Channel(self._api).listen()) as events:
            async for event in events:
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
