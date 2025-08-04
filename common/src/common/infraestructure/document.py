from uuid import UUID
from typing import Any, Annotated, get_args, get_origin

from google.cloud.firestore import AsyncDocumentReference
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    FieldSerializationInfo,
    ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler,
    field_validator
    
)
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import FieldValidationInfo


def Id():
    return Field(metadata={"id": True})


def Reference(collection_name: str = None):
    return (Field(metadata={"reference": True, "collection_name": collection_name}),)


def Collection(name: str = None, allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"subcollection": name})


class DocumentReference(BaseModel):
    path: str
    model_config = ConfigDict(frozen=True)


class MixinSerializer(BaseModel):
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
        return {k: v for k, v in data.items() if v is not None}

    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:
        model_fields = self.__class__.model_fields

        field_info = model_fields.get(info.field_name)
        if field_info:
            metadata = self.__get_custom_metadata(field_info)

            if metadata.get("id") is True:
                # Solo poner a None si es el documento raíz
                is_root = info.context and info.context.get("is_root", False)
                if is_root:
                    return None
            # Para documentos anidados, devolver el valor normal
                return str(value) if isinstance(value, UUID) else value

            if metadata.get("reference") is True:
                if value is not None:
                    return self.__get_document(value, metadata)
            

        return value

    def __get_custom_metadata(self, field_info: FieldInfo) -> dict:
        metadata = self.__get_metadata_from(field_info)
        if metadata:
            return metadata

        default = getattr(field_info, "default", None)
        if get_origin(default) is Annotated:
            for arg in get_args(default):
                if isinstance(arg, FieldInfo):
                    metadata = self.__get_metadata_from(arg)
                    if metadata:
                        return metadata

        return {}

    def __get_metadata_from(self, obj: Any) -> dict:
        schema_extra = getattr(obj, "json_schema_extra", None)
        if schema_extra:
            return schema_extra.get("metadata", {})
        return {}

    def __get_document(self, value, metadata):
        if not isinstance(value, Document):
            raise ValueError(
                f"El valor de referencia debe ser una instancia de Document, recibido: {type(value)}"
            )

        collection_name = (
            metadata.get("collection_name") or value.__class__.__name__.lower()
        )
        doc_id = str(value.id) if isinstance(value.id, UUID) else value.id
        return DocumentReference(f"{collection_name}/{doc_id}")
    
    

    model_config = ConfigDict(frozen=True)


class Document(MixinSerializer):
    id: UUID = Id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer): ...
