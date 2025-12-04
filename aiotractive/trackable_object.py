from .data_object import DataObject


class TrackableObject(DataObject):
    async def details(self):
        return await self._api.request(f"trackable_object/{self._id}")

    async def health_overview(self):
        """Get health overview data including activity, sleep, rest, and health metrics.
        
        Returns health_overview data from the APS API endpoint.
        Replaces the deprecated wellness_overview message.
        """
        return await self._api.aps_request(f"pet/{self._id}/health/overview")
