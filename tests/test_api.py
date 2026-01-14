"""Tests for the API client."""

from __future__ import annotations

from typing import Any

from aioresponses import aioresponses

from aiotractive import Tractive
from aiotractive.api import API

API_URL = str(API.API_URL)


def mock_auth(mock: aioresponses, auth_response: dict[str, Any]) -> None:
    """Add authentication endpoint mock to aioresponses."""
    mock.post(f"{API_URL}auth/token", payload=auth_response)


async def test_auth_success(auth_response: dict[str, Any]) -> None:
    """Test successful authentication returns user_id and access_token."""
    with aioresponses() as mock:
        mock_auth(mock, auth_response)

        async with Tractive("test@example.com", "password") as client:
            creds = await client.authenticate()

    assert creds is not None

    assert creds["user_id"] == "test_user_123"
    assert creds["access_token"] == "test_access_token_xyz"  # noqa: S105
