"""Exceptions for the Tractive REST API."""


class TractiveError(Exception):
    """Base Tractive Exception class."""


class UnauthorizedError(TractiveError):
    """When the server does not accept the API token."""


class NotFoundError(TractiveError):
    """When the server responds with 404."""


class DisconnectedError(TractiveError):
    """Channel disconnected."""
