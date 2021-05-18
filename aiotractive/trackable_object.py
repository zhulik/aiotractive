from .data_object import DataObject


class TrackableObject(DataObject):
    async def details(self):
        return await self._api.request(f"trackable_object/{self._id}")
