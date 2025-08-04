
from pydantic import( 
    BaseModel
)


from common import get_mapper

class FooDomain():
    def __init__(self, id:str,name:str, phone:str):
        self._id= id
        self._name = name
        self._phone = phone
    @property
    def id(self):
        return self._id
    @property
    def name(self):
        return self._name
    @property
    def phone(self):
        return self._phone

class Foo(BaseModel):
    id:str
    name:str
    phone:str

mapper = get_mapper(FooDomain,Foo)
foo = mapper.map(FooDomain("1","Antonio",""))
foo_domain = mapper.map(foo)


data = {
    "id":"123",
    "name":"Pedro",
    "phone":"616647015"
}
foo = Foo(**data)

print(foo)








