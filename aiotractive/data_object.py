from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from aiotractive.api import API


class DataObject:
    def __init__(self, api: "API", data: dict[str, Any]):
        self._api: "API" = api
        self._id: str = data["_id"]
        self.type: str = data["_type"]

    @override
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self._id} type={self.type}>"
