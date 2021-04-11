"""Low level client for the Tractive REST API."""

import asyncio
import aiohttp
from aiohttp.client_exceptions import ClientResponseError

from yarl import URL
import json

from .exceptions import UnauthorizedError


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

    async def authenticate(self):
        """Perform authenticateion."""

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
                  return await response.json()
              return await response.read()
            except ClientResponseError as error:
              if error.status in [401, 403]:
                raise UnauthorizedError from error

    async def close(self):
        """Close the session."""
        if self._session and self._close_session:
            await self._session.close()
