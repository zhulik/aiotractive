"""Representation of a Tractive tracker device."""

from .data_object import DataObject


class Tracker(DataObject):
    """Representation of a Tractive tracker device."""

    ACTIONS = {True: "on", False: "off"}

    async def details(self):
        """Get tracker details."""
        return await self._api.request(f"tracker/{self._id}")

    async def hw_info(self):
        """Get hardware info for the tracker."""
        return await self._api.request(f"device_hw_report/{self._id}/")

    async def pos_report(self):
        """Get position report for the tracker."""
        return await self._api.request(
            f"device_pos_report/{self._id}",
        )

    async def positions(self, time_from, time_to, fmt):
        """Get positions for the tracker within a time range."""
        url = f"tracker/{self._id}/positions"
        params = {
            "time_from": time_from,
            "time_to": time_to,
            "format": fmt,
        }
        return await self._api.request(url, params=params)

    async def set_buzzer_active(self, active):
        """Enable or disable the buzzer on the tracker."""
        action = self.ACTIONS[active]

        return await self._api.request(
            f"tracker/{self._id}/command/buzzer_control/{action}",
        )

    async def set_led_active(self, active):
        """Enable or disable the LED on the tracker."""
        action = self.ACTIONS[active]

        return await self._api.request(
            f"tracker/{self._id}/command/led_control/{action}",
        )

    async def set_live_tracking_active(self, active):
        """Enable or disable live tracking mode on the tracker."""
        action = self.ACTIONS[active]

        return await self._api.request(
            f"tracker/{self._id}/command/live_tracking/{action}",
        )
