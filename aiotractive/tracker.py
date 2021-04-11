from datetime import datetime, timedelta


class Tracker:
    DEFAULT_PERIOD_HOURS = 6

    def __init__(self, api, data):
        self._api = api
        self.id = data["_id"]
        self.type = data["_type"]
        self.version = data["_version"]

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id} type={self.type} version={self.version}>"

    async def hw_info(self):
        return await self._api.request(f"device_hw_report/{self.id}/")

    async def positions(
        self, time_from=datetime.now() - timedelta(hours=6), time_to=datetime.now()
    ):
        return await self._api.request(
            f"tracker/{self.id}/positions",
            params={
                "time_from": round(time_from.timestamp()),
                "time_to": round(time_to.timestamp()),
                "format": "json_segments",
            },
        )
