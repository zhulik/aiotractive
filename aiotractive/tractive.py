"""Entrypoint for the Tractive REST API."""

from .api import API


class Tractive:
    def __init__(self, *args, **kwargs):
        """Initialize the client."""
        self._api = API(*args, **kwargs)

    async def trackers(self):
      return await self._api.request(f"user/{await self._api.user_id()}/trackers")

    async def close(self):
        """Close open client session."""
        await self._api.close()

    async def __aenter__(self):
        """Async enter."""
        return self

    async def __aexit__(self, *exc_info):
        """Async exit."""
        await self.close()
