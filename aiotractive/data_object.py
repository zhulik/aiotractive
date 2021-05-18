class DataObject:
    def __init__(self, api, data):
        self._api = api
        self._id = data["_id"]
        self.type = data["_type"]

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self._id} type={self.type}>"
