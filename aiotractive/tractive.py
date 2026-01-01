"""Entrypoint for the Tractive REST API."""

from .api import API
from .channel import Channel
from .trackable_object import TrackableObject
from .tracker import Tracker


class Tractive:
    """Asynchronous Python client for the Tractive REST API."""

    def __init__(self, *args, **kwargs):
        """Initialize the client."""
        self._api = API(*args, **kwargs)

    async def authenticate(self):
        """Authenticate the client."""
        return await self._api.authenticate()

    async def trackers(self):
        """Get all trackers for the authenticated user."""
        trackers = await self._api.request(f"user/{await self._api.user_id()}/trackers")
        return [Tracker(self._api, t) for t in trackers]

    def tracker(self, tracker_id):
        """Get tracker by ID."""
        return Tracker(self._api, {"_id": tracker_id, "_type": "tracker"})

    def trackable_object(self, trackable_id):
        """Get trackable object by ID."""
        return TrackableObject(self._api, {"_id": trackable_id, "_type": "pet"})

    async def trackable_objects(self):
        """Get all trackable objects for the authenticated user."""
        objects = await self._api.request(
            f"user/{await self._api.user_id()}/trackable_objects",
        )
        return [TrackableObject(self._api, t) for t in objects]

    async def events(self):
        """Listen for real-time events from the Tractive API."""
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
