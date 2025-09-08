"""Low-level client for the Tractive REST API."""

import asyncio
import logging
import random

import time
from collections.abc import Callable
from typing import Any, Final

from aiohttp import ClientSession, ClientTimeout
from aiohttp.client_exceptions import ClientResponseError

from .exceptions import NotFoundError, TractiveError, UnauthorizedError


_LOGGER = logging.getLogger(__name__)


class API:
    API_URL: Final[str] = "https://graph.tractive.com/"

    def __init__(
        self,
        login: str,
        password: str,
        client_id: str,
        timeout: int = 10,
        loop: asyncio.AbstractEventLoop | None = None,
        session: ClientSession | None = None,
        retry_count: int = 3,
        retry_delay: int | float | Callable[[int], int | float] = (lambda attempt: 3**attempt + random.uniform(0, 3)),
    ) -> None:
        self._login: str = login
        self._password: str = password
        self._client_id: str = client_id
        self._timeout: int = timeout
        self._close_session: bool = False

        if session is None:
            loop = loop or asyncio.get_event_loop()
            self.session: ClientSession = ClientSession(raise_for_status=True)
            self._close_session = True

        self._user_credentials: UserCredentials = UserCredentials()

        self._retry_count: int = retry_count
        self._retry_delay: int | float | Callable[[int], int | float] = retry_delay

    async def user_id(self) -> str:
        assert await self.authenticate() is not None  # noqa: S101
        return self._user_credentials.user_id

    async def auth_headers(self) -> dict[str, str]:
        assert await self.authenticate() is not None  # noqa: S101
        return {**self.base_headers(), **self._user_credentials.headers}

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        """Perform request with error wrapping."""
        try:
            return await self.raw_request(*args, **kwargs)
        except ClientResponseError as error:
            if error.status in {401, 403}:
                raise UnauthorizedError from error
            if error.status == 404:
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
        api_version: str = "4",
        override_headers: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.API_URL}{api_version}/{uri}"

        headers = override_headers if override_headers is not None else await self.auth_headers()

        async with self.session.request(
            method,
            url=url,
            json=data,
            params=params,
            headers=headers,
            timeout=ClientTimeout(self._timeout),
        ) as response:
            _LOGGER.debug("Request %s, status: %s", response.url, response.status)

            if response.status == 400:
                raise TractiveError("Bad request")

            if response.status == 429:
                if attempt <= self._retry_count:
                    delay = self._retry_delay(attempt) if callable(self._retry_delay) else float(self._retry_delay)
                    _LOGGER.info("Request limit exceeded, retrying in %.1f seconds", delay)
                    await asyncio.sleep(delay)
                    return await self.raw_request(uri, params, data, method, attempt=attempt + 1)
                raise TractiveError("Request limit exceeded")

            if response.headers.get("Content-Type", "").startswith("application/json"):
                return await response.json()
            return await response.read()

    async def authenticate(self) -> dict[str, Any]:
        """Perform authentication."""
        if self._user_credentials and not self._user_credentials.is_expired:
            return self._user_credentials

        if not self._login or not self._password:
            raise UnauthorizedError("Missing login credentials")

        try:
            _LOGGER.debug("Requesting new credentials")
            data = {
                "platform_email": self._login,
                "platform_token": self._password,
                "grant_type": "tractive",
            }
            # raw_request expects JSON, not a string
            resp = await self.raw_request(
                "auth/token",
                data=data,
                method="POST",
                api_version="3",
                override_headers=self.base_headers(),
            )
        except ClientResponseError as err:
            if err.status in {401, 403}:
                raise UnauthorizedError from err
            raise TractiveError from err
        except Exception as err:
            raise TractiveError from err

        self._user_credentials = UserCredentials(resp)
        return self._user_credentials

    async def close(self) -> None:
        """Close the session."""
        if self.session and self._close_session:
            await self.session.close()

    def base_headers(self) -> dict[str, str]:
        return {
            "x-tractive-client": self._client_id,
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
        }


class UserCredentials(dict[str, Any]):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @property
    def user_id(self) -> str:
        return str(self["user_id"])

    @property
    def client_id(self) -> str:
        return str(self["client_id"])

    @property
    def expires_at(self) -> float:
        return float(self["expires_at"])

    @property
    def access_token(self) -> str:
        return str(self["access_token"])

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at - 3600  # Refresh 1 hour before expiry

    @property
    def headers(self) -> dict[str, str]:
        return {
            "x-tractive-user": self.user_id,
            "authorization": f"Bearer {self.access_token}",
        }
