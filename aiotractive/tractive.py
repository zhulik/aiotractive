"""Entrypoint for the Tractive REST API."""

from .api import API

from .tracker import Tracker


class Tractive:
    def __init__(self, *args, **kwargs):
        """Initialize the client."""
        self._api = API(*args, **kwargs)

    async def trackers(self):
        trackers = await self._api.request(f"user/{await self._api.user_id()}/trackers")
        return [Tracker(self._api, t) for t in trackers]

    async def close(self):
        """Close open client session."""
        await self._api.close()

    async def __aenter__(self):
        """Async enter."""
        return self

    async def __aexit__(self, *exc_info):
        """Async exit."""
        await self.close()
