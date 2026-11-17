"""Channel for real-time events from the Tractive REST API."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp
import orjson
from aiohttp.client_exceptions import ClientResponseError

from .api import API
from .exceptions import DisconnectedError, TractiveError, UnauthorizedError

_LOGGER = logging.getLogger(__name__)


class Channel:
    """Channel for real-time events from the Tractive REST API."""

    CHANNEL_URL = "https://channel.tractive.com/3/channel"
    IGNORE_MESSAGES = ("handshake", "keep-alive")

    KEEP_ALIVE_TIMEOUT = 60  # seconds
    CHECK_CONNECTION_TIME = 5  # seconds

    def __init__(
        self, api: API, on_connected: Callable[[], None] | None = None
    ) -> None:
        """Initialize the channel."""
        self._api = api
        self._on_connected = on_connected
        self._last_keep_alive: float | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._check_connection_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        self._retry_count = api.retry_count
        self._retry_delay = api.retry_delay

    async def listen(self) -> AsyncGenerator[dict[str, Any]]:
        """Listen for real-time events from the Tractive API."""
        self._check_connection_task = asyncio.create_task(self._check_connection())
        self._listen_task = asyncio.create_task(self._listen())
        self._listen_task.add_done_callback(self._on_listen_done)
        try:
            while True:
                event = await self._queue.get()
                self._queue.task_done()

                if event["type"] == "event":
                    yield event["event"]

                if event["type"] == "error":
                    raise event["error"]

                if event["type"] == "stopped":
                    raise DisconnectedError from event["error"]
        finally:
            # Cancel both before awaiting, so a second cancellation arriving
            # during the wait cannot orphan either task.
            tasks = [
                task
                for task in (self._check_connection_task, self._listen_task)
                if task is not None
            ]
            for task in tasks:
                task.cancel()
            await asyncio.wait(tasks)

    async def _listen(self) -> None:  # noqa: PLR0912, PLR0915
        if TYPE_CHECKING:
            assert self._api.session is not None

        exc: TractiveError
        failure: Exception

        attempt = 0
        while True:
            attempt += 1
            received_data = False
            try:
                headers = await self._api.auth_headers()
                _LOGGER.debug("Connecting to channel, attempt %s", attempt)
                # Supervise from before the request, so a stall while
                # connecting, awaiting headers or reading is caught alike.
                self._last_keep_alive = time.monotonic()
                async with self._api.session.request(
                    "POST",
                    self.CHANNEL_URL,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(
                        total=None,
                        connect=10,
                        sock_connect=10,
                        # Backstop only: the keep-alive watchdog normally
                        # fires first.
                        sock_read=2 * self.KEEP_ALIVE_TIMEOUT,
                        ceil_threshold=5,
                    ),
                ) as response:
                    _LOGGER.debug("Channel response status %s", response.status)
                    response.raise_for_status()
                    async for data in response.content:
                        if not received_data:
                            received_data = True
                            attempt = 0
                        event = orjson.loads(data)
                        if event["message"] == "keep-alive":
                            self._last_keep_alive = time.monotonic()
                            continue
                        if (
                            event["message"] == "handshake"
                            and self._on_connected is not None
                        ):
                            self._on_connected()
                        if event["message"] in self.IGNORE_MESSAGES:
                            continue
                        await self._queue.put({"type": "event", "event": event})
                failure = TractiveError("Channel stream closed by server")
            except (
                TimeoutError,
                aiohttp.ClientPayloadError,
                aiohttp.ServerDisconnectedError,
            ) as error:
                # The server periodically closes the long-lived stream
                # without a terminating chunk; after data that is normal.
                failure = error
            except ClientResponseError as error:
                if error.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                    # Non-recoverable failures
                    exc = UnauthorizedError(str(error))
                    exc.__cause__ = error
                    self._queue.put_nowait({"type": "error", "error": exc})
                    return
                if not (
                    error.status == HTTPStatus.TOO_MANY_REQUESTS
                    or error.status >= HTTPStatus.INTERNAL_SERVER_ERROR
                ):
                    # Other client errors, treat as non-recoverable
                    exc = TractiveError(str(error))
                    exc.__cause__ = error
                    self._queue.put_nowait({"type": "error", "error": exc})
                    return
                failure = error
            except TractiveError as error:
                self._queue.put_nowait({"type": "error", "error": error})
                return
            except Exception as error:  # noqa: BLE001
                exc = TractiveError(str(error))
                exc.__cause__ = error
                self._queue.put_nowait({"type": "error", "error": exc})
                return
            finally:
                # A stale stamp would let the watchdog cancel a retry sleep.
                self._last_keep_alive = None

            # Not repr(): it includes the request headers, token included.
            _LOGGER.debug(
                "Channel stream ended: %s: %s", type(failure).__name__, failure
            )
            if received_data:
                continue
            # A stream that connected but sent nothing is a failed attempt,
            # so a server that always goes silent ends in an error.
            if attempt > self._retry_count:
                # str(TimeoutError()) is empty.
                exc = TractiveError(str(failure) or type(failure).__name__)
                exc.__cause__ = failure
                self._queue.put_nowait({"type": "error", "error": exc})
                return
            delay = self._retry_delay(attempt)
            _LOGGER.debug("Retrying channel connection in %s s", delay)
            await asyncio.sleep(delay)

    def _on_listen_done(self, task: asyncio.Task[None]) -> None:
        # Queued after anything _listen queued, so listen() cannot wait forever
        # on a listener that was cancelled or died without saying why.
        error = None if task.cancelled() else task.exception()
        self._queue.put_nowait({"type": "stopped", "error": error})

    async def _check_connection(self) -> None:
        try:
            while True:
                if self._last_keep_alive is not None and (
                    time.monotonic() - self._last_keep_alive > self.KEEP_ALIVE_TIMEOUT
                ):
                    _LOGGER.debug(
                        "No keep-alive for %s s, cancelling channel listener",
                        self.KEEP_ALIVE_TIMEOUT,
                    )
                    if self._listen_task is not None:
                        self._listen_task.cancel()
                    return

                await asyncio.sleep(self.CHECK_CONNECTION_TIME)
        except asyncio.CancelledError:
            return
