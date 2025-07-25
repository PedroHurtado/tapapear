import uuid;
from dataclasses import dataclass,field

def document(cls=None, *, kw_only=False):
    def wrap(c):
        return dataclass(c, unsafe_hash=True, kw_only=kw_only)
    
    if cls is None:
        return wrap
    return wrap(cls)

def Id():    
    return field(metadata={"id": True})


def Collection(name: str = None, allow_none: bool = False):
    return field(default=None if allow_none else ..., metadata={"subcollection": name})

def Reference(allow_none: bool = False):
    return field(default=None if allow_none else ..., metadata={"reference": True})


@dataclass
class Document:
    id:uuid = Id()
    def __eq__(self, value):
        return isinstance(value,Document) and value.id == self.id
    def __hash__(self):
        return hash(self.id)
    