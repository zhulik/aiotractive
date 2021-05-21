from .data_object import DataObject


class Tracker(DataObject):
    ACTIONS = {True: "on", False: "off"}

    async def details(self):
        return await self._api.request(f"tracker/{self._id}")

    async def hw_info(self):
        return await self._api.request(f"device_hw_report/{self._id}/")

    async def pos_report(self):
        return await self._api.request(
            f"device_pos_report/{self._id}",
        )

    async def set_buzzer_active(self, active):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/buzzer_control/{action}")

    async def set_led_active(self, active):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/led_control/{action}")

    async def set_live_tracking_active(self, active):
        action = self.ACTIONS[active]

        return await self._api.request(f"tracker/{self._id}/command/live_tracking/{action}")
