from uuid import UUID
from typing import Any
from pydantic import( 
    BaseModel, Field, field_serializer,FieldSerializationInfo,ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler
    
)
from .firestore_util import(
    get_document
)


def Id():
    return Field(metadata={"id": True})

def Reference(collection_name: str = None):    
    return Field(metadata={"reference": True, "collection_name": collection_name})

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
            if metadata.get('reference') is True:
                if value is not None:
                    return self.__get_document(value, metadata)
                    
        if isinstance(value,UUID):
            return str(value)
        
        return value   
    def __get_document(self, value, metadata):
        """Función privada para obtener la referencia del documento"""
        # Validar que value es una instancia de Document
        if not isinstance(value, Document):
            raise ValueError(f"El valor de referencia debe ser una instancia de Document, recibido: {type(value)}")
        
        # Obtener el nombre de la colección del metadata o del nombre de la clase
        collection_name = metadata.get('collection_name')
        if not collection_name:
            collection_name = value.__class__.__name__.lower()
        
        # Crear y retornar la referencia del documento
        return get_document(collection_name, value.id)
    model_config = ConfigDict(
        frozen=True,    
    )
        
    
class Embeddable(MixinSerializer):...