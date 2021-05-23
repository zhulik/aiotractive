"""Low level client for the Tractive REST API."""

import asyncio
import json
import time

import aiohttp
from aiohttp.client_exceptions import ClientResponseError
from yarl import URL

from .exceptions import NotFoundError, TractiveError, UnauthorizedError

CLIENT_ID = "5728aa1fc9077f7c32000186"


class API:  # pylint: disable=too-many-instance-attributes
    API_URL = URL("https://graph.tractive.com/3/")

    DEFAULT_TIMEOUT = 10

    TOKEN_URI = "auth/token"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        login,
        password,
        client_id=CLIENT_ID,
        timeout=DEFAULT_TIMEOUT,
        loop=None,
        session=None,
    ):
        self._login = login
        self._password = password
        self._client_id = client_id
        self._timeout = timeout

        self.session = session
        self._close_session = False

        if self.session is None:
            loop = loop or asyncio.get_event_loop()
            self.session = aiohttp.ClientSession(loop=loop)
            self._close_session = True

        self._user_credentials = None
        self._auth_headers = None

    async def user_id(self):
        await self.authenticate()
        return self._user_credentials["user_id"]

    async def auth_headers(self):
        await self.authenticate()
        return {**self.base_headers(), **self._auth_headers}

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
        async with self.session.request(
            method,
            self.API_URL.join(URL(uri)).update_query(params),
            json=data,
            headers=await self.auth_headers(),
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            if "Content-Type" in response.headers and "application/json" in response.headers["Content-Type"]:
                return await response.json()
            return await response.read()

    async def authenticate(self):
        """Perform authenticateion."""
        if self._user_credentials is not None and self._user_credentials["expires_at"] - time.time() < 3600:
            self._user_credentials = None
            self._auth_headers = None

        if self._user_credentials is not None:
            return self._user_credentials

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
                timeout=self._timeout,
            ) as response:
                try:
                    response.raise_for_status()
                    if "Content-Type" in response.headers and "application/json" in response.headers["Content-Type"]:
                        self._user_credentials = await response.json()
                        self._auth_headers = {
                            "x-tractive-user": self._user_credentials["user_id"],
                            "authorization": f"Bearer {self._user_credentials['access_token']}",
                        }
                        return self._user_credentials
                except ClientResponseError as error:
                    if error.status in [401, 403]:
                        raise UnauthorizedError from error
                except Exception as error:
                    raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

    async def close(self):
        """Close the session."""
        if self.session and self._close_session:
            await self.session.close()

    def base_headers(self):
        return {
            "x-tractive-client": self._client_id,
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
        }
