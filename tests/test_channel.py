"""Tests for channel module."""

from __future__ import annotations

import asyncio
from asyncio.exceptions import TimeoutError as AIOTimeoutError
from http import HTTPStatus
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientResponse
from aiohttp.client_exceptions import ClientResponseError

from aiotractive.channel import Channel
from aiotractive.exceptions import TractiveError, UnauthorizedError


@pytest.fixture
def mock_api() -> MagicMock:
    """Create a mock API instance."""
    api = MagicMock()
    api.auth_headers = AsyncMock(return_value={"Authorization": "Bearer test"})

    return api


@pytest.fixture
def channel(mock_api: MagicMock) -> Channel:
    """Create a Channel instance with mocked API."""
    return Channel(mock_api)


def create_mock_response(events: list[bytes]) -> MagicMock:
    """Create a mock response with async iterator over events."""
    response = MagicMock(spec=ClientResponse)
    response.content = AsyncIterator(events)

    return response


class AsyncIterator:
    """Async iterator for mocking response.content."""

    def __init__(self, items: list[bytes]) -> None:
        """Initialize."""
        self.items = iter(items)
        self._exhausted = asyncio.Event()

    def __aiter__(self) -> AsyncIterator:
        """Async iterator enter."""
        return self

    async def __anext__(self) -> bytes:
        """Get next item asynchronously."""
        try:
            return next(self.items)
        except StopIteration:
            # Block indefinitely until cancelled, simulating waiting for more data
            await self._exhausted.wait()
            raise StopAsyncIteration from None


async def test_listen_receives_event(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen puts valid events into the queue."""
    event_data = b'{"message": "test_event", "data": {"id": "123"}}'
    mock_response = create_mock_response([event_data])

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_api.session.request.return_value = mock_context

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert events
    assert len(events) == 2  # One event + one cancelled event
    event = events[0]
    assert event["event"]["message"] == "test_event"
    assert event["event"]["data"] == {"id": "123"}


async def test_listen_multiple_events(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen processes multiple events in sequence."""
    input_events = [
        b'{"message": "keep-alive"}',
        b'{"message": "tracker_status", "id": "1"}',
        b'{"message": "handshake"}',
        b'{"message": "position", "id": "2"}',
    ]
    mock_response = create_mock_response(input_events)

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_api.session.request.return_value = mock_context

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    assert channel._last_keep_alive is not None

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert len(events) == 3  # Two events + one cancelled event
    assert events[0]["event"]["message"] == "tracker_status"
    assert events[1]["event"]["message"] == "position"


async def test_listen_keep_alive(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen updates _last_keep_alive on keep-alive message."""
    event_data = b'{"message": "keep-alive"}'
    mock_response = create_mock_response([event_data])

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_api.session.request.return_value = mock_context

    assert channel._last_keep_alive is None

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    assert channel._last_keep_alive is not None

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    # Queue should only have the cancelled event, no keep-alive events
    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "cancelled"


async def test_listen_handshake(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen ignores handshake messages."""
    event_data = b'{"message": "handshake"}'
    mock_response = create_mock_response([event_data])

    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_response
    mock_api.session.request.return_value = mock_context

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    # Queue should only have the cancelled event, no keep-alive events
    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "cancelled"


async def test_listen_timeout(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen continues loop on AIOTimeoutError."""
    call_count = 0

    def side_effect(*args: Any, **kwargs: Any) -> AsyncMock:  # noqa: ANN401,ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise AIOTimeoutError
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = create_mock_response(
            [b'{"message": "tracker_status"}']
        )
        return mock_context

    mock_api.session.request.side_effect = side_effect

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    assert call_count >= 2


async def test_listen_unauthorized_401(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen handles 401 ClientResponseError."""
    exc = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=HTTPStatus.UNAUTHORIZED,
        message="Unauthorized",
    )
    mock_api.session.request.side_effect = exc

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "error"
    assert isinstance(event["error"], UnauthorizedError)
    assert event["error"].__cause__ is exc


async def test_listen_unauthorized_404(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen handles 404 ClientResponseError."""
    exc = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=HTTPStatus.NOT_FOUND,
        message="Not found",
    )
    mock_api.session.request.side_effect = exc

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "error"
    assert isinstance(event["error"], TractiveError)
    assert event["error"].__cause__ is exc


async def test_listen_exception(channel: Channel, mock_api: MagicMock) -> None:
    """Test that _listen handles generic exceptions."""
    exc = ValueError("Something went wrong")
    mock_api.session.request.side_effect = exc

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "error"
    assert isinstance(event["error"], TractiveError)
    assert event["error"].__cause__ is exc
