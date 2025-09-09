"""Entrypoint for the Tractive REST API."""

from collections.abc import Iterable
import logging

from aiotractive.exceptions import TractiveError
from .channel import Channel
import asyncio
import random
from typing import Any, Callable

from aiohttp import ClientSession
from .trackable_object import TrackableObject
from .tracker import Tracker

from aiotractive.api import API

_LOGGER = logging.getLogger(__name__)


class Tractive:
    def __init__(
        self,
        login: str,
        password: str,
        *,
        timeout: int = 10,
        client_id: str = "625e533dc3c3b41c28a669f0",
        loop: asyncio.AbstractEventLoop | None = None,
        session: ClientSession | None = None,
        retry_count: int = 3,
        retry_delay: int | float | Callable[[int], int | float] = (lambda attempt: 3**attempt + random.uniform(0, 3)),
    ) -> None:
        """Initialize the client."""
        self._api: "API" = API(
            login=login,
            password=password,
            client_id=client_id,
            timeout=timeout,
            loop=loop,
            session=session,
            retry_count=retry_count,
            retry_delay=retry_delay,
        )

    async def authenticate(self):
        return await self._api.authenticate()

    async def trackers(self):
        trackers = await self._api.request(f"user/{await self._api.user_id()}/trackers")
        return [Tracker(self._api, t) for t in trackers]

    async def bulk_send(self, items: Iterable[dict[str, str]]) -> list[dict[str, Any]]:
        """
        Send many objects in one round-trip.
        Each item must contain at least `_id` and `_type`.
        """
        if not items:
            return []

        # If the caller gives us a generator we only want to iterate once
        items = list(items)
        _LOGGER.debug("Bulk-sending %d item(s)", len(items))

        try:
            return await self._api.bulk_post(items)
        except Exception as exc:
            _LOGGER.error("Bulk request failed: %s", exc)
            raise TractiveError("Bulk request failed") from exc

    def tracker(self, tracker_id: str):
        return Tracker(self._api, {"_id": tracker_id, "_type": "tracker"})

    async def trackable_objects(self):
        objects = await self._api.request(f"user/{await self._api.user_id()}/trackable_objects")
        return [TrackableObject(self._api, t) for t in objects]

    async def events(self):
        async for event in Channel(self._api).listen():
            yield event

    async def close(self):
        """Close open client session."""
        await self._api.close()

    async def __aenter__(self):
        """Async enter."""
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()
