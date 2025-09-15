from common.util import ID
class BaseEntity:
    def __init__(self, id:ID):
        self._id = id
    @property
    def id(self):
        return self._id
    def __eq__(self, value):
        return isinstance(value,BaseEntity) and self.id == value.id
    def __hash__(self):
        return hash(self.id)