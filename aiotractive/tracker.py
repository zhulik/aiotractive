class Tracker:
    def __init__(self, api, data):
        self._api = api
        self.id = data["_id"]
        self.type = data["_type"]
        self.version = data["_version"]

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id} type={self.type} veersion={self.version}>"

    async def hw_info(self):
        return await self._api.request(f"device_hw_report/{self.id}/")
