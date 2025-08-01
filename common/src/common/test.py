from typing import Annotated, Any, Union

from pydantic import BaseModel, BeforeValidator, ValidationError,Field


class Document(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
def ensure_list(value: Any) -> Any:
    return value

class B:
    pass
class Model(Document):
    numbers: Annotated[
        Union[Document|B|None],
        BeforeValidator(ensure_list),
        Field(metadata={"reference": True, "collection_name": "test"}),
    ]
    name:str
    


print(Model(numbers=B(),name="Hola"))
# > numbers=[2]
try:
    Model(numbers="str",name="Pedro")
    print("Fin")
except ValidationError as err:
    print(err)
    """
    1 validation error for Model
    numbers.0
      Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='str', input_type=str]
    """
