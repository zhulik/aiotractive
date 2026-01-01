"""Representation of a Tractive trackable object (pet)."""

from .data_object import DataObject


class TrackableObject(DataObject):
    """Representation of a Tractive trackable object (pet)."""

    async def details(self):
        """Get trackable object details."""
        return await self._api.request(f"trackable_object/{self._id}")

    async def health_overview(self):
        """Get health overview data including activity, sleep, rest, and health metrics.

        Returns health_overview data from the APS API endpoint.
        Replaces the deprecated wellness_overview message.
        """
        return await self._api.request(
            f"pet/{self._id}/health/overview",
            base_url=self._api.APS_API_URL,
        )
