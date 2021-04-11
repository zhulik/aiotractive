from datetime import datetime, timedelta

from .data_object import DataObject


class Tracker(DataObject):
    DEFAULT_PERIOD_HOURS = 6

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
