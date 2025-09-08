from datetime import datetime
from .data_object import DataObject


def _to_unix(t: int | float | datetime) -> float:
    """Convert int/float/datetime → unix timestamp (float)."""
    if isinstance(t, datetime):
        return t.timestamp()
    return float(t)


class Tracker(DataObject):
    ACTIONS: dict[bool, str] = {True: "on", False: "off"}

    async def details(self):
        return await self._api.request(f"tracker/{self._id}", api_version=3)

    async def hw_info(self):
        return await self._api.request(f"device_hw_report/{self._id}/")

    async def pos_report(self):
        return await self._api.request(
            f"device_pos_report/{self._id}",
        )

    async def positions(
        self,
        time_from: int | float | datetime,
        time_to: int | float | datetime,
        fmt: str,
    ):
        """Positions between two instants (API expects unix floats)."""
        url = f"tracker/{self._id}/positions"
        params: dict[str, float | str] = {
            "time_from": _to_unix(time_from),
            "time_to": _to_unix(time_to),
            "format": fmt,
        }
        return await self._api.request(url, params=params)

    async def set_buzzer_active(self, active: bool):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/buzzer_control/{action}")

    async def set_led_active(self, active: bool):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/led_control/{action}")

    async def set_live_tracking_active(self, active: bool):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/live_tracking/{action}")
