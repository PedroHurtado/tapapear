
from common.infraestructure import(
    Document,
    Reference,
    initialize_database,
    transactional    
)
from common.domain import(
    ValueObject
)
from uuid import uuid4, UUID
from typing import Optional


class Data(ValueObject):
    name:str

data = Data(name="Pedro")
        



class Bar(Document): 
    name: str

class Foo(Document):
    bar: Bar
    x: Optional[UUID] = None

bar = Bar(id=uuid4(), name="Test")
foo = Foo(id=uuid4(), bar=bar)  # x omitido

print("Document:",foo)
d = foo.model_dump()
print("Serializado:", d)
