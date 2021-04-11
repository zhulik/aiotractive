"""Low level client for the Tractive REST API."""

import asyncio
import aiohttp
from aiohttp.client_exceptions import ClientResponseError

from yarl import URL
import json

from .exceptions import TractiveError, UnauthorizedError, NotFoundError


class API:
    API_URL = URL("https://graph.tractive.com/3/")
    TRACTIVE_CLIENT = "5f9be055d8912eb21a4cd7ba"
    DEFAULT_TIMEOUT = 10

    TOKEN_URI = "auth/token"

    BASE_HEADERS = {
        "x-tractive-client": TRACTIVE_CLIENT,
        "content-type": "application/json;charset=UTF-8",
        "accept": "application/json, text/plain, */*",
    }

    def __init__(
        self, login, password, timeout=DEFAULT_TIMEOUT, loop=None, session=None
    ):
        self._login = login
        self._password = password
        self._timeout = timeout

        self._loop = loop or asyncio.get_event_loop()
        self._session = session
        self._close_session = False

        if self._session is None:
            self._session = aiohttp.ClientSession(loop=self._loop)
            self._close_session = True

        self._user_credentials = None

    async def user_id(self):
        await self._authenticate()
        return self._user_credentials["user_id"]

    async def request(self, *args, **kwargs):
        """Perform request with error wrapping."""
        try:
            return await self.raw_request(*args, **kwargs)
        except aiohttp.client_exceptions.ClientResponseError as error:
            if error.status in [401, 403]:
                raise UnauthorizedError from error
            if error.status == 404:
                raise NotFoundError from error
            raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

    async def raw_request(self, uri, params=None, data=None, method="GET"):
        """Perform request."""
        await self._authenticate()
        async with self._session.request(
            method,
            self.API_URL.join(URL(uri)).update_query(params),
            json=data,
            headers={**self.BASE_HEADERS, **self._auth_headers},
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            if (
                "Content-Type" in response.headers
                and "application/json" in response.headers["Content-Type"]
            ):
                return await response.json()
            return await response.read()

    async def _authenticate(self):
        """Perform authenticateion."""
        # TODO: update credentials if expired
        if self._user_credentials is not None:
            return self._user_credentials

        async with self._session.request(
            "POST",
            self.API_URL.join(URL(self.TOKEN_URI)),
            data=json.dumps(
                {
                    "platform_email": self._login,
                    "platform_token": self._password,
                    "grant_type": "tractive",
                }
            ),
            headers=self.BASE_HEADERS,
            timeout=self._timeout,
        ) as response:
            try:
                response.raise_for_status()
                if (
                    "Content-Type" in response.headers
                    and "application/json" in response.headers["Content-Type"]
                ):
                    self._user_credentials = await response.json()
                    self._auth_headers = {
                        "x-tractive-user": self._user_credentials["user_id"],
                        "authorization": f"Bearer {self._user_credentials['access_token']}",
                    }
                    return self._user_credentials
            except ClientResponseError as error:
                if error.status in [401, 403]:
                    raise UnauthorizedError from error

    async def close(self):
        """Close the session."""
        if self._session and self._close_session:
            await self._session.close()
