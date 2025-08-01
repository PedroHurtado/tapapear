from common.infraestructure import(
    Document,
    Reference
)
from common.domain import(
    ValueObject
)
from uuid import uuid4, UUID
from typing import Optional

class Data(ValueObject):
    name:str
    def _validate(self):...
data = Data("Pedro")
data1 = Data("Pedro")

print(data==data1)
data.name ="pedro hurtado"
my_set =set()
my_set.add(data)

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
