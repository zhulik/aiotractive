from __future__ import annotations

import asyncio
import json
import time
from asyncio.exceptions import TimeoutError as AIOTimeoutError
from collections.abc import AsyncGenerator
from typing import Any

from aiohttp.client_exceptions import ClientResponseError

from aiotractive.api import API
from .exceptions import DisconnectedError, TractiveError, UnauthorizedError


class Channel:
    CHANNEL_URL: str = "https://channel.tractive.com/3/channel"
    IGNORE_MESSAGES: tuple[str, ...] = ("handshake", "keep-alive")

    KEEP_ALIVE_TIMEOUT: float = 60.0
    CHECK_CONNECTION_TIME: float = 5.0

    def __init__(self, api: API) -> None:
        self._api: API = api
        self._last_keep_alive: float | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._check_connection_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def listen(self) -> AsyncGenerator[dict[str, Any], None]:
        """Yield channel events until disconnection / error."""
        self._check_connection_task = asyncio.create_task(self._check_connection())
        self._listen_task = asyncio.create_task(self._listen())

        while True:
            event: dict[str, Any] = await self._queue.get()
            self._queue.task_done()

            if event["type"] == "event":
                yield event["event"]

            elif event["type"] == "error":
                await self._cancel_tasks()
                raise event["error"]

            elif event["type"] == "cancelled":
                await self._cancel_tasks()
                raise DisconnectedError() from event["error"]

    # ---------- internal helpers ----------
    async def _listen(self) -> None:
        """Long-poll the channel endpoint."""
        while True:
            try:
                async with self._api.session.request(
                    "POST", self.CHANNEL_URL, headers=await self._api.auth_headers()
                ) as response:
                    async for data in response.content:
                        event: dict[str, Any] = json.loads(data)

                        if event.get("message") == "keep-alive":
                            self._last_keep_alive = time.time()
                            continue
                        if event.get("message") in self.IGNORE_MESSAGES:
                            continue

                        await self._queue.put({"type": "event", "event": event})

            except AIOTimeoutError:
                continue

            except ClientResponseError as err:
                if err.status in {401, 403}:
                    await self._queue.put({"type": "error", "error": UnauthorizedError(err)})
                else:
                    await self._queue.put({"type": "error", "error": TractiveError(err)})
                return

            except asyncio.CancelledError as cancel:
                await self._queue.put({"type": "cancelled", "error": cancel})
                return

            except Exception as exc:  # pylint: disable=broad-except
                await self._queue.put({"type": "error", "error": TractiveError(exc)})
                return

    async def _check_connection(self) -> None:
        """Watch-dog: cancel listener if keep-alive times out."""
        try:
            while True:
                if self._last_keep_alive is not None and time.time() - self._last_keep_alive > self.KEEP_ALIVE_TIMEOUT:
                    if self._listen_task and not self._listen_task.done():
                        _ = self._listen_task.cancel()
                    return
                await asyncio.sleep(self.CHECK_CONNECTION_TIME)
        except asyncio.CancelledError:
            return

    async def _cancel_tasks(self) -> None:
        """Cancel internal background tasks."""
        if self._check_connection_task and not self._check_connection_task.done():
            _ = self._check_connection_task.cancel()
            await self._check_connection_task
        if self._listen_task and not self._listen_task.done():
            _ = self._listen_task.cancel()
            await self._listen_task
