from typing import Annotated, TypeVar, Union,List, get_origin,get_args, Any, Type
from pydantic import( 
    BaseModel, BeforeValidator, Field,field_serializer, FieldSerializationInfo,
    ValidationError,
    model_validator,
    field_validator
)
from pydantic_core.core_schema import FieldValidationInfo
T = TypeVar("T")




class Document(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    @field_validator("*",mode='before')
    @classmethod    
    def __validate_before(cls,value:Any, info:FieldValidationInfo):
        #print(info.field_name)
        field =  cls.model_fields.get(info.field_name)
        print(field.annotation)
        return value


class B(Document):
    name:str
def ensure_list(value, info:FieldValidationInfo):    
    return value

def Reference():
    return Field(metadata={"reference": True, "collection_name": "test"})
    



NumbersType = Annotated[
    B,
    BeforeValidator(ensure_list),
    Field(metadata={"reference": True, "collection_name": "test"})
]


class Model(Document):
    numbers: B = Reference()
    name: str

    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:
        model_fields = self.__class__.model_fields
        field_info = model_fields.get(info.field_name)

        tipo = field_info.annotation

        if tipo and get_origin(tipo) is Union:
            tipos = get_args(tipo)
            primer_tipo = tipos[0]
            print(f"Es Union, primer tipo: {primer_tipo}")
        return value
   



Model(numbers=B(name="Pedro"), name="Hola")


