import asyncio
import json
import time
from asyncio.exceptions import TimeoutError as AIOTimeoutError

from aiohttp.client_exceptions import ClientResponseError

from .exceptions import DisconnectedError, TractiveError, UnauthorizedError


class Channel:
    CHANNEL_URL = "https://channel.tractive.com/3/channel"
    IGNORE_MESSAGES = ["handshake", "keep-alive"]

    KEEP_ALIVE_TIMEOUT = 7  # seconds
    CHECK_CONNECTION_TIME = 4  # seconds

    def __init__(self, api):
        self._api = api
        self._last_keep_alive = None
        self._listen_task = None
        self._check_connection_task = None
        self._queue = asyncio.Queue()

    async def listen(self):
        self._check_connection_task = asyncio.create_task(self._check_connection())
        self._listen_task = asyncio.create_task(self._listen())
        while True:
            event = await self._queue.get()
            self._queue.task_done()

            if event["type"] == "event":
                yield event["event"]

            if event["type"] == "error":
                self._check_connection_task.cancel()
                await self._check_connection_task

                self._listen_task.cancel()
                await self._listen_task

                raise event["error"]

            if event["type"] == "cancelled":
                self._listen_task.cancel()

                await self._listen_task
                raise DisconnectedError() from event["error"]

    async def _listen(self):
        while True:
            try:
                async with self._api.session.request(
                    "POST", self.CHANNEL_URL, headers=await self._api.auth_headers()
                ) as response:
                    async for data, _ in response.content.iter_chunks():
                        event = json.loads(data)
                        if event["message"] == "keep-alive":
                            self._last_keep_alive = time.time()
                            continue
                        if event["message"] in self.IGNORE_MESSAGES:
                            continue
                        await self._queue.put({"type": "event", "event": event})
            except AIOTimeoutError:
                continue
            except ClientResponseError as error:
                try:
                    if error.status in [401, 403]:
                        raise UnauthorizedError from error
                    raise TractiveError from error
                except TractiveError as error:
                    await self._queue.put({"type": "error", "error": error})
                    return

            except asyncio.CancelledError as error:
                await self._queue.put({"type": "cancelled", "error": error})
                return

            except Exception as error:  # pylint: disable=broad-except
                try:
                    raise TractiveError from error
                except TractiveError as error:
                    await self._queue.put({"type": "error", "error": error})
                    return

    async def _check_connection(self):
        try:
            while True:
                if self._last_keep_alive is not None and (
                    time.time() - self._last_keep_alive > self.KEEP_ALIVE_TIMEOUT
                ):
                    self._listen_task.cancel()
                    return

                await asyncio.sleep(self.CHECK_CONNECTION_TIME)
        except asyncio.CancelledError:
            return
