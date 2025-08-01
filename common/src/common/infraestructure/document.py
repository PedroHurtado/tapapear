from uuid import UUID
from typing import Any, Union, Annotated, get_args, get_origin

from google.cloud.firestore import AsyncDocumentReference
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    FieldSerializationInfo,
    ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler,
    BeforeValidator,
)
from pydantic.fields import FieldInfo

from .firestore_util import get_document


def Id():
    return Field(metadata={"id": True})


class MixinSerializer(BaseModel):
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
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
        if field_info:
            metadata = self.__get_custom_metadata(field_info)

            if metadata.get("id") is True:
                return None

            if metadata.get("reference") is True:
                if value is not None:
                    return self.__get_document(value, metadata)

            if isinstance(value, UUID):
                return str(value)

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
        return get_document(collection_name, value.id)

    model_config = ConfigDict(frozen=True)


class Embeddable(MixinSerializer): ...


def ensure_reference(value: Union[Document | AsyncDocumentReference, None]):
    if value is None:
        return value
    if isinstance(value, AsyncDocumentReference):
        return value


def Reference(collection_name: str = None):
    return Annotated[
        Union[Document | AsyncDocumentReference, None],
        BeforeValidator(ensure_reference),
        Field(metadata={"reference": True, "collection_name": collection_name}),
    ]


def Collection(name: str = None, allow_none: bool = False):
    default = None if allow_none else ...
    return Field(default, metadata={"subcollection": name})
