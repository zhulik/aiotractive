"""Tests for channel module."""

from __future__ import annotations

import asyncio
import contextlib
from asyncio.exceptions import TimeoutError as AIOTimeoutError
from http import HTTPStatus
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from aiohttp import ClientPayloadError, ClientResponse, ServerDisconnectedError
from aiohttp.client_exceptions import ClientResponseError

from aiotractive.channel import Channel
from aiotractive.exceptions import DisconnectedError, TractiveError, UnauthorizedError


@pytest.fixture
def mock_api() -> MagicMock:
    """Create a mock API instance."""
    api = MagicMock()
    api.auth_headers = AsyncMock(return_value={"Authorization": "Bearer test"})
    api.retry_count = 3
    api.retry_delay = MagicMock(return_value=0.1)

    return api


@pytest.fixture
def channel(mock_api: MagicMock) -> Channel:
    """Create a Channel instance with mocked API."""
    return Channel(mock_api)


def create_mock_response(
    events: list[bytes], raise_after: Exception | None = None
) -> MagicMock:
    """Create a mock response with async iterator over events."""
    response = MagicMock(spec=ClientResponse)
    response.content = AsyncIterator(events, raise_after)
    response.status = 200
    response.request_info = MagicMock()
    response.history = ()
    response.reason = "OK"
    return response


class AsyncIterator:
    """Async iterator for mocking response.content."""

    def __init__(
        self, items: list[bytes], raise_after: Exception | None = None
    ) -> None:
        """Initialize."""
        self.items = iter(items)
        self._raise_after = raise_after
        self._exhausted = asyncio.Event()

    def __aiter__(self) -> AsyncIterator:
        """Async iterator enter."""
        return self

    async def __anext__(self) -> bytes:
        """Get next item asynchronously."""
        try:
            return next(self.items)
        except StopIteration:
            if self._raise_after is not None:
                raise self._raise_after from None
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
    mock_api.retry_delay.return_value = 0

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
    mock_api.retry_delay.return_value = 0
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


async def test_listen_retry_on_429_client_error(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that _listen retries on 429 ClientResponseError."""
    call_count = 0

    def side_effect(*args: Any, **kwargs: Any) -> AsyncMock:  # noqa: ANN401,ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=HTTPStatus.TOO_MANY_REQUESTS,
                message="Too Many Requests",
            )
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = create_mock_response(
            [b'{"message": "tracker_status"}']
        )
        return mock_context

    mock_api.session.request.side_effect = side_effect

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.2)
    task.cancel()
    await task

    assert call_count >= 2
    assert cast(MagicMock, channel._retry_delay).called


async def test_listen_retry_exhausted_on_429(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that _listen gives up after exhausting retries on 429."""
    mock_api.retry_count = 1

    exc = ClientResponseError(
        request_info=MagicMock(),
        history=(),
        status=HTTPStatus.TOO_MANY_REQUESTS,
        message="Too Many Requests",
    )
    mock_api.session.request.side_effect = exc

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.5)
    task.cancel()

    events = []
    while not channel._queue.empty():
        events.append(await channel._queue.get())

    assert events
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "error"
    assert isinstance(event["error"], TractiveError)
    assert "Too Many Requests" in str(event["error"])


def mock_channel_stream(mock_api: MagicMock, events: list[bytes]) -> None:
    """Make the mocked session stream the given raw events."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = create_mock_response(events)
    mock_api.session.request.return_value = mock_context


@pytest.mark.parametrize(
    ("events", "expected_calls"),
    [
        ([b'{"message": "handshake"}'], 1),
        ([b'{"message": "handshake"}', b'{"message": "keep-alive"}'], 1),
        ([b'{"message": "keep-alive"}', b'{"message": "tracker_status"}'], 0),
    ],
)
async def test_listen_on_connected(
    mock_api: MagicMock, events: list[bytes], expected_calls: int
) -> None:
    """Test that on_connected is called only for handshake messages."""
    on_connected = MagicMock()
    channel = Channel(mock_api, on_connected=on_connected)
    mock_channel_stream(mock_api, events)

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    assert on_connected.call_count == expected_calls
    events_in_queue = []
    while not channel._queue.empty():
        events_in_queue.append(await channel._queue.get())
    assert all(
        item["type"] != "event" or item["event"]["message"] != "handshake"
        for item in events_in_queue
    )


async def test_listen_handshake_without_on_connected(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that a handshake without on_connected callback does not fail."""
    mock_channel_stream(mock_api, [b'{"message": "handshake"}'])

    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.1)
    task.cancel()
    await task

    assert (await channel._queue.get())["type"] == "cancelled"


def assert_internal_tasks_done(channel: Channel) -> None:
    """Assert both internal channel tasks are finished."""
    assert channel._listen_task is not None
    assert channel._check_connection_task is not None
    assert channel._listen_task.done()
    assert channel._check_connection_task.done()


async def test_listen_aclose_cleans_up(channel: Channel, mock_api: MagicMock) -> None:
    """Test that closing the listen generator cancels internal tasks."""
    mock_channel_stream(mock_api, [b'{"message": "tracker_status", "id": "1"}'])

    async with contextlib.aclosing(channel.listen()) as gen:
        event = await anext(gen)
        assert event["message"] == "tracker_status"

    assert_internal_tasks_done(channel)


async def test_listen_consumer_cancel_cleans_up(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that cancelling the consumer propagates and cancels internal tasks."""
    mock_channel_stream(mock_api, [b'{"message": "tracker_status", "id": "1"}'])
    received = asyncio.Event()

    async def consume() -> None:
        async for _ in channel.listen():
            received.set()

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert received.is_set()
    assert_internal_tasks_done(channel)


@pytest.mark.parametrize(
    ("side_effect", "expected_exception"),
    [
        (ValueError("boom"), TractiveError),
        (
            ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=HTTPStatus.UNAUTHORIZED,
                message="Unauthorized",
            ),
            UnauthorizedError,
        ),
    ],
)
async def test_listen_error_cleans_up(
    channel: Channel,
    mock_api: MagicMock,
    side_effect: Exception,
    expected_exception: type[Exception],
) -> None:
    """Test that errors propagate from listen and internal tasks are cleaned up."""
    mock_api.session.request.side_effect = side_effect

    with pytest.raises(expected_exception):
        async for _ in channel.listen():
            pass

    assert_internal_tasks_done(channel)


async def test_listen_auth_headers_unauthorized(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that an UnauthorizedError from auth_headers is raised unchanged."""
    error = UnauthorizedError("expired")
    mock_api.auth_headers = AsyncMock(side_effect=error)

    with pytest.raises(UnauthorizedError) as exc_info:
        async for _ in channel.listen():
            pass

    assert exc_info.value is error
    assert_internal_tasks_done(channel)


async def test_listen_disconnected_cleans_up(
    channel: Channel, mock_api: MagicMock
) -> None:
    """Test that a cancelled internal listener raises DisconnectedError."""
    mock_channel_stream(mock_api, [])
    gen = channel.listen()
    task = asyncio.create_task(anext(gen))
    await asyncio.sleep(0.1)
    assert channel._listen_task is not None
    channel._listen_task.cancel()

    with pytest.raises(DisconnectedError):
        await task

    assert_internal_tasks_done(channel)


def create_mock_context(
    events: list[bytes], raise_after: Exception | None = None
) -> AsyncMock:
    """Create a request context manager yielding a mock response."""
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = create_mock_response(events, raise_after)
    return mock_context


def drain(channel: Channel) -> list[dict[str, Any]]:
    """Return all items currently in the channel queue."""
    items = []
    while not channel._queue.empty():
        items.append(channel._queue.get_nowait())
    return items


async def run_listen(channel: Channel) -> None:
    """Run _listen briefly, then cancel it."""
    task = asyncio.create_task(channel._listen())
    await asyncio.sleep(0.3)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


STREAM_CLOSED_ERRORS = [
    ClientPayloadError("Response payload is not completed"),
    ServerDisconnectedError(),
]


@pytest.mark.parametrize("stream_error", STREAM_CLOSED_ERRORS)
async def test_listen_stream_closed_after_data_reconnects_silently(
    mock_api: MagicMock, stream_error: Exception
) -> None:
    """Test that a stream closed after data reconnects without error or backoff."""
    on_connected = MagicMock()
    channel = Channel(mock_api, on_connected=on_connected)
    mock_api.session.request.side_effect = [
        create_mock_context(
            [b'{"message": "handshake"}', b'{"message": "position", "id": "1"}'],
            stream_error,
        ),
        create_mock_context(
            [b'{"message": "handshake"}', b'{"message": "position", "id": "2"}']
        ),
    ]

    await run_listen(channel)

    items = [item for item in drain(channel) if item["type"] != "cancelled"]
    assert [item["type"] for item in items] == ["event", "event"]
    assert [item["event"]["id"] for item in items] == ["1", "2"]
    assert on_connected.call_count == 2
    mock_api.retry_delay.assert_not_called()
    assert mock_api.session.request.call_count == 2


@pytest.mark.parametrize("stream_error", STREAM_CLOSED_ERRORS)
async def test_listen_stream_closed_before_data_backs_off_then_errors(
    mock_api: MagicMock, stream_error: Exception
) -> None:
    """Test that a stream closed before any data backs off and then gives up."""
    mock_api.retry_count = 2
    mock_api.retry_delay.return_value = 0
    channel = Channel(mock_api)
    mock_api.session.request.side_effect = [
        create_mock_context([], stream_error) for _ in range(3)
    ]

    await run_listen(channel)

    items = drain(channel)
    assert len(items) == 1
    assert items[0]["type"] == "error"
    assert isinstance(items[0]["error"], TractiveError)
    assert items[0]["error"].__cause__ is stream_error
    assert mock_api.retry_delay.call_args_list == [call(1), call(2)]
    assert mock_api.session.request.call_count == 3


async def test_listen_retry_counter_resets_after_successful_connection(
    mock_api: MagicMock,
) -> None:
    """Test that receiving data resets the retry counter."""
    mock_api.retry_count = 1
    mock_api.retry_delay.return_value = 0
    channel = Channel(mock_api)

    def server_error() -> ClientResponseError:
        return ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            message="Internal Server Error",
        )

    mock_api.session.request.side_effect = [
        server_error(),
        create_mock_context(
            [b'{"message": "position", "id": "1"}'],
            ClientPayloadError("Response payload is not completed"),
        ),
        server_error(),
        create_mock_context([b'{"message": "position", "id": "2"}']),
    ]

    await run_listen(channel)

    items = [item for item in drain(channel) if item["type"] != "cancelled"]
    assert [item["type"] for item in items] == ["event", "event"]
    assert mock_api.retry_delay.call_args_list == [call(1), call(1)]
    assert mock_api.session.request.call_count == 4
