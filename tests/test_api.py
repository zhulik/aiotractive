"""Tests for the API client."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest
from aiohttp.client_exceptions import ClientResponseError
from aiointercept import aiointercept

from aiotractive import Tractive
from aiotractive.api import API
from aiotractive.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    TractiveError,
    UnauthorizedError,
)

API_URL = str(API.API_URL)


def mock_auth(mock: aiointercept, auth_response: dict[str, Any]) -> None:
    """Add authentication endpoint mock to aiointercept."""
    mock.post(f"{API_URL}auth/token", payload=auth_response)


async def test_auth_success(auth_response: dict[str, Any]) -> None:
    """Test successful authentication returns user_id and access_token."""
    async with aiointercept(mock_external_urls=True) as mock:
        mock_auth(mock, auth_response)

        async with Tractive("test@example.com", "password") as client:
            creds = await client.authenticate()

    assert creds is not None

    assert creds["user_id"] == "test_user_123"
    assert creds["access_token"] == "test_access_token_xyz"  # noqa: S105


async def test_request_retries_429_and_preserves_client_error_cause(
    auth_response: dict[str, Any],
) -> None:
    """Test that request() preserves ClientResponseError as TractiveError.__cause__."""
    async with aiointercept(mock_external_urls=True) as mock:
        mock_auth(mock, auth_response)
        url = f"{API_URL}user/{auth_response['user_id']}/trackers"
        mock.get(url, status=HTTPStatus.TOO_MANY_REQUESTS, repeat=True)

        api = API(
            "test@example.com",
            "password",
            retry_count=2,
            retry_delay=lambda _attempt: 0,
        )
        with pytest.raises(TractiveError) as exc_info:
            await api.request(f"user/{auth_response['user_id']}/trackers")

        await api.close()

    cause = exc_info.value.__cause__
    assert isinstance(cause, ClientResponseError)
    assert cause.status == HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (HTTPStatus.UNAUTHORIZED, UnauthorizedError),
        (HTTPStatus.FORBIDDEN, ForbiddenError),
        (HTTPStatus.NOT_FOUND, NotFoundError),
        (HTTPStatus.BAD_REQUEST, BadRequestError),
        (HTTPStatus.INTERNAL_SERVER_ERROR, TractiveError),
    ],
)
async def test_request_maps_http_status_to_exception(
    auth_response: dict[str, Any], status: HTTPStatus, expected: type[TractiveError]
) -> None:
    """Test that request() maps HTTP error statuses to the library exceptions."""
    async with aiointercept(mock_external_urls=True) as mock:
        mock_auth(mock, auth_response)
        uri = f"user/{auth_response['user_id']}/trackers"
        mock.get(f"{API_URL}{uri}", status=status)

        api = API("test@example.com", "password")
        with pytest.raises(expected) as exc_info:
            await api.request(uri)
        await api.close()

    assert type(exc_info.value) is expected
    cause = exc_info.value.__cause__
    assert isinstance(cause, ClientResponseError)
    assert cause.status == status
