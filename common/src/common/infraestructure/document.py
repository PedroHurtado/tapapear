from uuid import UUID
from typing import Any
from pydantic import( 
    BaseModel, Field, field_serializer,FieldSerializationInfo,ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler
    
)
from pydantic_core import PydanticUndefined

def Id():
    return Field(metadata={"id": True})

def Reference(allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"reference": True})

def Collection(name: str = None, allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"subcollection": name})

from pydantic import BaseModel
from typing import Any

class MixinSerializer(BaseModel):
    @model_serializer(mode='wrap')
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)        
       
        # Remover campos con valor None
        return {k: v for k, v in data.items() if v is not None}
    
class Document(MixinSerializer):
    id: UUID = Id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id) 
    
    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:       
        
        model_fields = self.__class__.model_fields
        field_info = model_fields.get(info.field_name)
        
        if field_info and getattr(field_info, 'json_schema_extra', None):
            metadata = field_info.json_schema_extra.get('metadata', {})
            if metadata.get("id") is True:
                return None
                    
        if isinstance(value,UUID):
            return str(value)
        
        return value   
   
    model_config = ConfigDict(
        frozen=True,    
    )
        
    
class Embeddable(MixinSerializer):...