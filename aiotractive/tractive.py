"""Entrypoint for the Tractive REST API."""

from .api import API
from .channel import Channel
from .trackable_object import TrackableObject
from .tracker import Tracker


class Tractive:
    def __init__(self, *args, **kwargs):
        """Initialize the client."""
        self._api = API(*args, **kwargs)

    async def authenticate(self):
        return await self._api.authenticate()

    async def trackers(self):
        trackers = await self._api.request(f"user/{await self._api.user_id()}/trackers")
        return [Tracker(self._api, t) for t in trackers]

    def tracker(self, tracker_id):
        return Tracker(self._api, {"_id": tracker_id, "_type": "tracker"})

    def trackable_object(self, trackable_id):
        return TrackableObject(self._api, {"_id": trackable_id, "_type": "pet"})

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

    async def __aexit__(self, *exc_info):
        """Async exit."""
        await self.close()
