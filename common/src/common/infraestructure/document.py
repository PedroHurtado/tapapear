from uuid import UUID
from pydantic import BaseModel, Field

def Id():
    return Field(metadata={"id": True})

def Reference(allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"reference": True})

def Collection(name: str = None, allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"subcollection": name})

class Document(BaseModel):
    id: UUID = Id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)

    class Config:
        frozen = True  # Opcional: útil si quieres que sea hashable e inmutable
