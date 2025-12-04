"""Low level client for the Tractive REST API."""

import asyncio
import json
import logging
import random
import time

import aiohttp
from aiohttp.client_exceptions import ClientResponseError
from yarl import URL

from .exceptions import NotFoundError, TractiveError, UnauthorizedError

CLIENT_ID = "625e533dc3c3b41c28a669f0"

_LOGGER = logging.getLogger(__name__)


class API:  # pylint: disable=too-many-instance-attributes
    API_URL = URL("https://graph.tractive.com/3/")
    APS_API_URL = URL("https://aps-api.tractive.com/api/1/")

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
        retry_count=3,
        retry_delay=lambda attempt: 4**attempt + random.uniform(0, 3),
    ):
        self._login = login
        self._password = password
        self._client_id = client_id
        self._timeout = timeout

        self.session = session
        self._close_session = False

        if self.session is None:
            loop = loop or asyncio.get_event_loop()
            self.session = aiohttp.ClientSession(raise_for_status=True)
            self._close_session = True

        self._user_credentials = None
        self._auth_headers = None

        self._retry_count = retry_count
        self._retry_delay = retry_delay

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
        except ClientResponseError as error:
            if error.status in [401, 403]:
                raise UnauthorizedError from error
            if error.status == 404:
                raise NotFoundError from error
            raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

    async def aps_request(self, *args, **kwargs):
        """Perform request to APS API with error wrapping."""
        try:
            return await self.raw_request(*args, base_url=self.APS_API_URL, **kwargs)
        except ClientResponseError as error:
            if error.status in [401, 403]:
                raise UnauthorizedError from error
            if error.status == 404:
                raise NotFoundError from error
            raise TractiveError from error
        except Exception as error:
            raise TractiveError from error

    async def raw_request(  # pylint: disable=too-many-arguments
        self, uri, params=None, data=None, method="GET", attempt: int = 1, base_url=None
    ):
        """Perform request."""
        if base_url is None:
            base_url = self.API_URL
        
        async with self.session.request(
            method,
            base_url.join(URL(uri)).update_query(params),
            json=data,
            headers=await self.auth_headers(),
            timeout=self._timeout,
        ) as response:
            _LOGGER.debug("Request %s, status: %s", response.url, response.status)

            if response.status == 429:
                if attempt <= self._retry_count:
                    delay = self._retry_delay(attempt)
                    _LOGGER.info("Request limit exceeded, retrying in %s second", delay)
                    await asyncio.sleep(delay)
                    return await self.raw_request(uri, params, data, method, attempt=attempt + 1, base_url=base_url)
                raise TractiveError("Request limit exceeded")

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
