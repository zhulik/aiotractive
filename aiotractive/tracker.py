"""Representation of a Tractive tracker device."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from .data_object import DataObject

if TYPE_CHECKING:
    from .api import API
    from .models import TrackerStatus


class Tracker(DataObject):
    """Representation of a Tractive tracker device."""

    ACTIONS: ClassVar[dict[bool, str]] = {True: "on", False: "off"}

    def __init__(
        self, api: API, data: dict[str, Any], status: TrackerStatus | None = None
    ) -> None:
        """Initialize the tracker, optionally bound to a live status."""
        super().__init__(api, data)
        self._status = status

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
        return pos_report or {}

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
        if self._status is not None and result.get("pending"):
            self._status.buzzer = active
        return result

    async def set_led_active(self, active: bool) -> dict[str, Any]:
        """Enable or disable the LED on the tracker."""
        action = self.ACTIONS[active]
        result: dict[str, Any] = await self._api.request(
            f"tracker/{self._id}/command/led_control/{action}"
        )
        if self._status is not None and result.get("pending"):
            self._status.led = active
        return result

    async def set_live_tracking_active(self, active: bool) -> dict[str, Any]:
        """Enable or disable live tracking mode on the tracker."""
        action = self.ACTIONS[active]
        result: dict[str, Any] = await self._api.request(
            f"tracker/{self._id}/command/live_tracking/{action}"
        )
        if self._status is not None and result.get("pending"):
            self._status.live_tracking = active
        return result
