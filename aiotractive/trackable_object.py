"""Representation of a Tractive trackable object (pet)."""

import logging
from typing import Any

from .data_object import DataObject
from .exceptions import BadRequestError, ForbiddenError

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

        Returns an empty dict when the pet has no health overview: the API
        responds with 400 for pets that do not support it and with 403 when
        the subscription of the assigned tracker is inactive.
        """
        try:
            health_overview: dict[str, Any] = await self._api.request(
                f"pet/{self._id}/health/overview",
                base_url=self._api.APS_API_URL,
            )
        except (BadRequestError, ForbiddenError) as error:
            _LOGGER.info(
                "Health overview is not available for trackable object %s (%s)",
                self._id,
                type(error).__name__,
            )
            return {}
        return health_overview
