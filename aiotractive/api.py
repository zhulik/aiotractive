"""Low level client for the Tractive REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp.client_exceptions import ClientResponseError
from yarl import URL

from .exceptions import NotFoundError, TractiveError, UnauthorizedError

CLIENT_ID = "625e533dc3c3b41c28a669f0"

_LOGGER = logging.getLogger(__name__)


class API:
    """Client for the API handling auth, requests, retries, and error mapping."""

    API_URL = URL("https://graph.tractive.com/4/")
    APS_API_URL = URL("https://aps-api.tractive.com/api/1/")

    DEFAULT_TIMEOUT = 10

    TOKEN_URI = "auth/token"  # noqa: S105

    def __init__(
        self,
        login: str,
        password: str,
        client_id: str = CLIENT_ID,
        timeout: int = DEFAULT_TIMEOUT,
        loop: asyncio.AbstractEventLoop | None = None,
        session: aiohttp.ClientSession | None = None,
        retry_count: int = 3,
        retry_delay: Callable[[int], float] = lambda attempt: 4**attempt
        + random.uniform(0, 3),  # noqa: S311
    ) -> None:
        """Initialize."""
        self._login = login
        self._password = password
        self._client_id = client_id
        self._timeout = timeout

        self.session: aiohttp.ClientSession | None = session
        self._close_session: bool = False

        if self.session is None:
            loop = loop or asyncio.get_event_loop()
            self.session = aiohttp.ClientSession(raise_for_status=True)
            self._close_session = True

        self._user_credentials: dict[str, Any] | None = None
        self._auth_headers: dict[str, str] | None = None

        self._retry_count = retry_count
        self._retry_delay = retry_delay

    async def user_id(self) -> str:
        """Get user ID."""
        await self.authenticate()
        if TYPE_CHECKING:
            assert self._user_credentials is not None
        user_id: str = self._user_credentials["user_id"]
        return user_id

    async def auth_headers(self) -> dict[str, str]:
        """Get authentication headers."""
        await self.authenticate()
        if TYPE_CHECKING:
            assert self._auth_headers is not None
        return {**self.base_headers(), **self._auth_headers}

    async def request(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        """Perform request with error wrapping."""
        try:
            return await self.raw_request(*args, **kwargs)
        except ClientResponseError as error:
            if error.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise UnauthorizedError from error
            if error.status == HTTPStatus.NOT_FOUND:
                raise NotFoundError from error
            raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

    async def raw_request(
        self,
        uri: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        method: str = "GET",
        attempt: int = 1,
        base_url: URL = API_URL,
    ) -> Any:  # noqa: ANN401
        """Perform request."""
        if TYPE_CHECKING:
            assert self.session is not None
        async with self.session.request(
            method,
            base_url.join(URL(uri)).update_query(params),
            json=data,
            headers=await self.auth_headers(),
            timeout=aiohttp.ClientTimeout(total=self._timeout),
        ) as response:
            _LOGGER.debug("Request %s, status: %s", response.url, response.status)

            if response.status == HTTPStatus.TOO_MANY_REQUESTS:
                if attempt <= self._retry_count:
                    delay = self._retry_delay(attempt)
                    _LOGGER.info("Request limit exceeded, retrying in %s second", delay)
                    await asyncio.sleep(delay)
                    return await self.raw_request(
                        uri,
                        params,
                        data,
                        method,
                        attempt=attempt + 1,
                        base_url=base_url,
                    )
                raise TractiveError("Request limit exceeded")

            if (
                "Content-Type" in response.headers
                and "application/json" in response.headers["Content-Type"]
            ):
                return await response.json()
            return await response.read()

    async def authenticate(self) -> dict[str, Any] | None:
        """Perform authentication."""
        if (
            self._user_credentials is not None
            and self._user_credentials["expires_at"] - time.time() < 3600  # noqa: PLR2004
        ):
            self._user_credentials = None
            self._auth_headers = None

        if self._user_credentials is not None:
            return self._user_credentials

        if TYPE_CHECKING:
            assert self.session is not None
        try:
            async with self.session.request(
                "POST",
                self.API_URL.join(URL(self.TOKEN_URI)),
                data=json.dumps(
                    {
                        "platform_email": self._login,
                        "platform_token": self._password,
                        "grant_type": "tractive",
                    }
                ),
                headers=self.base_headers(),
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            ) as response:
                if (
                    "Content-Type" in response.headers
                    and "application/json" in response.headers["Content-Type"]
                ):
                    self._user_credentials = await response.json()
                    self._auth_headers = {
                        "x-tractive-user": self._user_credentials["user_id"],
                        "authorization": (
                            f"Bearer {self._user_credentials['access_token']}"
                        ),
                    }
                    return self._user_credentials
        except ClientResponseError as error:
            if error.status in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]:
                raise UnauthorizedError from error
            raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

        return None

    async def close(self) -> None:
        """Close the session."""
        if self.session and self._close_session:
            await self.session.close()

    def base_headers(self) -> dict[str, str]:
        """Get base headers."""
        return {
            "x-tractive-client": self._client_id,
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
        }
