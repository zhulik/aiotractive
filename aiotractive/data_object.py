"""Base class for Tractive data objects."""


class DataObject:
    """Base class for Tractive data objects."""

    def __init__(self, api, data):
        """Initialize the data object."""
        self._api = api
        self._id = data["_id"]
        self.type = data["_type"]

    def __repr__(self):
        """Return string representation of the data object."""
        return f"<{self.__class__.__name__} id={self._id} type={self.type}>"
