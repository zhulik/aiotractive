"""Tests driving the real Channel against a local fake streaming server."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from http import HTTPStatus
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiotractive.channel import Channel
from aiotractive.exceptions import DisconnectedError, TractiveError

# The retry delay outlasts KEEP_ALIVE_TIMEOUT + CHECK_CONNECTION_TIME so a stale
# keep-alive stamp expires while _listen is still sleeping between retries.
KEEP_ALIVE_TIMEOUT = 0.2
CHECK_CONNECTION_TIME = 0.05
RETRY_DELAY = 0.3
RETRY_COUNT = 3
# Three retries of RETRY_DELAY fit comfortably; a hang trips this quickly.
BOUND = 2.0

HANDSHAKE = b'{"message": "handshake"}\n'
KEEP_ALIVE = b'{"message": "keep-alive"}\n'
EVENT_1 = b'{"message": "tracker_status", "n": 1}\n'
EVENT_2 = b'{"message": "tracker_status", "n": 2}\n'
AUTHORIZATION = "Bearer secret-token-4711"

Behaviour = Callable[[web.Request, asyncio.Event], Awaitable[web.StreamResponse]]


async def _open_stream(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse()
    await response.prepare(request)
    return response


def _serve_lines_then_close(*lines: bytes) -> Behaviour:
    async def behaviour(
        request: web.Request, _stop: asyncio.Event
    ) -> web.StreamResponse:
        response = await _open_stream(request)
        for line in lines:
            await response.write(line)
        await response.write_eof()
        return response

    return behaviour


def _serve_lines_then_silence(*lines: bytes) -> Behaviour:
    async def behaviour(
        request: web.Request, stop: asyncio.Event
    ) -> web.StreamResponse:
        response = await _open_stream(request)
        for line in lines:
            await response.write(line)
        await stop.wait()
        return response

    return behaviour


def _respond_with_status(status: HTTPStatus) -> Behaviour:
    async def behaviour(
        _request: web.Request, _stop: asyncio.Event
    ) -> web.StreamResponse:
        return web.Response(status=status)

    return behaviour


async def _never_respond(
    _request: web.Request, stop: asyncio.Event
) -> web.StreamResponse:
    # Accept the request but never send headers.
    await stop.wait()
    return web.Response()


async def _drop_connection(
    request: web.Request, _stop: asyncio.Event
) -> web.StreamResponse:
    # Abort the socket before any response so the client sees a bare disconnect.
    assert request.transport is not None
    request.transport.abort()
    raise ConnectionResetError


@dataclass
class FakeServer:
    """Scriptable server: first connection and later ones behave differently."""

    first: Behaviour
    later: Behaviour
    connections: int = 0

    def __post_init__(self) -> None:
        """Prepare the stop flag and per-connection arrival events."""
        self.stop = asyncio.Event()
        self._arrived: defaultdict[int, asyncio.Event] = defaultdict(asyncio.Event)

    async def wait_for_connection(self, number: int) -> None:
        """Wait until the given (1-based) connection has reached the server."""
        await self._arrived[number].wait()

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """Dispatch the request to the behaviour scripted for its number."""
        self.connections += 1
        number = self.connections
        self._arrived[number].set()
        behaviour = self.first if number == 1 else self.later
        return await behaviour(request, self.stop)


@dataclass
class Env:
    """Everything a test needs: the server, the channel and the connect hook."""

    server: FakeServer
    channel: Channel
    on_connected: MagicMock


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink the watchdog timings so each test takes fractions of a second."""
    monkeypatch.setattr(Channel, "KEEP_ALIVE_TIMEOUT", KEEP_ALIVE_TIMEOUT)
    monkeypatch.setattr(Channel, "CHECK_CONNECTION_TIME", CHECK_CONNECTION_TIME)


@contextlib.asynccontextmanager
async def stream_env(
    monkeypatch: pytest.MonkeyPatch, first: Behaviour, later: Behaviour
) -> AsyncGenerator[Env]:
    """Run a fake server plus a real session and channel, then tear all down."""
    fake = FakeServer(first, later)
    app = web.Application()
    app.router.add_post("/channel", fake.handle)
    server = TestServer(app)
    await server.start_server()
    monkeypatch.setattr(Channel, "CHANNEL_URL", str(server.make_url("/channel")))

    api = MagicMock()
    api.auth_headers = AsyncMock(return_value={"Authorization": AUTHORIZATION})
    api.retry_count = RETRY_COUNT
    api.retry_delay = MagicMock(return_value=RETRY_DELAY)
    on_connected = MagicMock()
    try:
        async with aiohttp.ClientSession() as session:
            api.session = session
            yield Env(fake, Channel(api, on_connected), on_connected)
    finally:
        # Release handlers parked in silence so the server can shut down.
        fake.stop.set()
        await server.close()


async def _drain(channel: Channel) -> None:
    async with contextlib.aclosing(channel.listen()) as events:
        async for _ in events:
            pass


async def _collect(channel: Channel, count: int) -> list[int]:
    seen: list[int] = []
    async with contextlib.aclosing(channel.listen()) as events:
        async for event in events:
            seen.append(event["n"])
            if len(seen) == count:
                break
    return seen


@pytest.mark.parametrize(
    "later",
    [
        _respond_with_status(HTTPStatus.TOO_MANY_REQUESTS),
        _respond_with_status(HTTPStatus.SERVICE_UNAVAILABLE),
        _drop_connection,
    ],
)
async def test_listen_raises_when_reconnects_keep_failing(
    monkeypatch: pytest.MonkeyPatch, later: Behaviour
) -> None:
    """Consumer gets an error instead of hanging once every reconnect fails."""
    first = _serve_lines_then_close(HANDSHAKE, KEEP_ALIVE, EVENT_1)
    async with stream_env(monkeypatch, first, later) as env:
        with pytest.raises(TractiveError) as exc_info:
            async with asyncio.timeout(BOUND):
                await _drain(env.channel)
    # DisconnectedError is a TractiveError too, so this also rules out the
    # watchdog killing the listener during its retry sleep.
    assert not isinstance(exc_info.value, DisconnectedError)


@pytest.mark.parametrize(
    "silent",
    [
        _never_respond,
        _serve_lines_then_silence(),
        _serve_lines_then_silence(KEEP_ALIVE),
    ],
)
async def test_listen_raises_disconnected_when_stream_goes_silent(
    monkeypatch: pytest.MonkeyPatch, silent: Behaviour
) -> None:
    """Silence before headers, after headers or after a keep-alive ends listening."""
    async with stream_env(monkeypatch, silent, silent) as env:
        with pytest.raises(DisconnectedError):
            async with asyncio.timeout(BOUND):
                await _drain(env.channel)


async def test_listen_keeps_delivering_events_after_clean_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Events flow from the second connection and on_connected fires again."""
    # Only reconnection is under test; keep the watchdog out of the race.
    monkeypatch.setattr(Channel, "KEEP_ALIVE_TIMEOUT", BOUND)
    first = _serve_lines_then_close(HANDSHAKE, EVENT_1)
    second = _serve_lines_then_silence(HANDSHAKE, EVENT_2)
    async with stream_env(monkeypatch, first, second) as env:
        async with asyncio.timeout(BOUND):
            seen = await _collect(env.channel, 2)

        assert seen == [1, 2]
        assert env.on_connected.call_count == 2


async def test_cancelling_consumer_during_retries_leaves_no_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling the consumer mid-retry stops both internal tasks."""
    first = _serve_lines_then_close(HANDSHAKE, EVENT_1)
    later = _respond_with_status(HTTPStatus.SERVICE_UNAVAILABLE)
    async with stream_env(monkeypatch, first, later) as env:
        consumer = asyncio.create_task(_drain(env.channel))
        async with asyncio.timeout(BOUND):
            await env.server.wait_for_connection(2)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)

        assert env.channel._listen_task is not None
        assert env.channel._check_connection_task is not None
        assert env.channel._listen_task.done()
        assert env.channel._check_connection_task.done()


@pytest.mark.parametrize(
    "status", [HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.SERVICE_UNAVAILABLE]
)
async def test_debug_logs_never_contain_authorization(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: HTTPStatus,
) -> None:
    """Failed attempts are logged without the Authorization header value."""
    caplog.set_level(logging.DEBUG, logger="aiotractive.channel")
    failing = _respond_with_status(status)
    async with stream_env(monkeypatch, failing, failing) as env:
        with pytest.raises(TractiveError):
            async with asyncio.timeout(BOUND):
                await _drain(env.channel)

    messages = [record.getMessage() for record in caplog.records]
    assert any(message.startswith("Channel response status") for message in messages)
    assert any(message.startswith("Channel stream ended") for message in messages)
    assert not any(AUTHORIZATION in message for message in messages)
