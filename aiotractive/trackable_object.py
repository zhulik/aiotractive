"""Representation of a Tractive trackable object (pet)."""

import logging
from typing import Any

from .data_object import DataObject
from .exceptions import BadRequestError

_LOGGER = logging.getLogger(__name__)


class TrackableObject(DataObject):
    """Representation of a Tractive trackable object (pet)."""

    async def details(self) -> dict[str, Any]:
        """Get trackable object details."""
        trackable_object: dict[str, Any] = await self._api.request(
            f"trackable_object/{self._id}"
        )
        return trackable_object

    async def health_overview(self) -> dict[str, Any]:
        """Get health overview data including activity, sleep, rest, and health metrics.

        Returns health_overview data from the APS API endpoint.
        Replaces the deprecated wellness_overview message.
        """
        try:
            health_overview: dict[str, Any] = await self._api.request(
                f"pet/{self._id}/health/overview",
                base_url=self._api.APS_API_URL,
            )
        except BadRequestError:
            _LOGGER.info(
                "Trackable object %s does not support health/overview", self._id
            )
            return {}
        return health_overview
