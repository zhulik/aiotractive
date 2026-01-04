"""Tests for channel module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientResponse

from aiotractive.channel import Channel


@pytest.fixture
def mock_api() -> MagicMock:
    """Create a mock API instance."""
    api = MagicMock()
    api.auth_headers = AsyncMock(return_value={"Authorization": "Bearer test"})

    return api


@pytest.fixture
def channel(mock_api) -> Channel:
    """Create a Channel instance with mocked API."""
    return Channel(mock_api)


def create_mock_response(events) -> MagicMock:
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


@pytest.mark.asyncio
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

    events = []
    events.append(await channel._queue.get())

    assert events
    event = events[0]
    assert event["event"]["message"] == "test_event"
    assert event["event"]["data"] == {"id": "123"}
