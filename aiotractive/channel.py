import json
from asyncio.exceptions import TimeoutError as AIOTimeoutError


class Channel:
    CHANNEL_URL = "https://channel.tractive.com/3/channel"
    IGNORE_MESSAGES = ["handshake", "keep-alive"]

    def __init__(self, api):
        self._api = api

    async def listen(self):
        while True:
            try:
                async with self._api.session.request(
                    "POST", self.CHANNEL_URL, headers=await self._api.auth_headers()
                ) as response:
                    async for data, _ in response.content.iter_chunks():
                        event = json.loads(data)
                        if event["message"] in self.IGNORE_MESSAGES:
                            continue
                        yield event
            except AIOTimeoutError:
                continue
