"""Representation of a Tractive tracker device."""

from typing import Any, ClassVar

from .data_object import DataObject


class Tracker(DataObject):
    """Representation of a Tractive tracker device."""

    ACTIONS: ClassVar[dict[bool, str]] = {True: "on", False: "off"}

    async def details(self) -> dict[str, Any]:
        """Get tracker details."""
        details: dict[str, Any] = await self._api.request(f"tracker/{self._id}")
        return details

    async def hw_info(self) -> dict[str, Any]:
        """Get hardware info for the tracker."""
        hw_info: dict[str, Any] = await self._api.request(
            f"device_hw_report/{self._id}/"
        )
        return hw_info or {}

    async def pos_report(self) -> dict[str, Any]:
        """Get position report for the tracker."""
        pos_report: dict[str, Any] = await self._api.request(
            f"device_pos_report/{self._id}"
        )
        return pos_report

    async def positions(
        self, time_from: float, time_to: float, fmt: str
    ) -> dict[str, Any]:
        """Get positions for the tracker within a time range."""
        url = f"tracker/{self._id}/positions"
        params = {
            "time_from": time_from,
            "time_to": time_to,
            "format": fmt,
        }
        positions: dict[str, Any] = await self._api.request(url, params=params)
        return positions

    async def set_buzzer_active(self, active: bool) -> dict[str, Any]:
        """Enable or disable the buzzer on the tracker."""
        action = self.ACTIONS[active]
        result: dict[str, Any] = await self._api.request(
            f"tracker/{self._id}/command/buzzer_control/{action}"
        )
        return result

    async def set_led_active(self, active: bool) -> dict[str, Any]:
        """Enable or disable the LED on the tracker."""
        action = self.ACTIONS[active]
        result: dict[str, Any] = await self._api.request(
            f"tracker/{self._id}/command/led_control/{action}"
        )
        return result

    async def set_live_tracking_active(self, active: bool) -> dict[str, Any]:
        """Enable or disable live tracking mode on the tracker."""
        action = self.ACTIONS[active]
        result: dict[str, Any] = await self._api.request(
            f"tracker/{self._id}/command/live_tracking/{action}"
        )
        return result
