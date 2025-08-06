
from uuid import UUID,uuid4
from pydantic import( 
    BaseModel
)
str_uuid = str(uuid4()) 
class Foo(BaseModel):
    id:UUID

foo = Foo(id=str_uuid)

print(foo)










