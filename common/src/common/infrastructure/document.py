from uuid import UUID
from typing import Any, Annotated, get_args, get_origin
from common.util import get_id
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    FieldSerializationInfo,
    ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler,
    SerializationInfo,
)
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import FieldValidationInfo
from common.inflect import plural


def id():
    return Field(metadata={"id": True}, default_factory=lambda:get_id())


def reference(collection_name: str = None):
    return Field(metadata={"reference": True, "collection_name": collection_name})


def collection(collection_name: str = None):
    return Field(metadata={"subcollection": collection_name, "_is_subcollection": True})


class DocumentReference(BaseModel):
    path: str
    model_config = ConfigDict(frozen=True)

   
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo):
        data = serializer(self)
        if info.mode == 'json':
            return data
        else:
            return DocumentReference(**data)


class CollectionReference(BaseModel):
    path: str
    model_config = ConfigDict(frozen=True)

    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo):
        data = serializer(self)
        # ✅ Mantener consistencia con DocumentReference
        if info.mode == 'json':
            return data
        else:
            return CollectionReference(**data)


class MixinSerializer(BaseModel):
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
        if not isinstance(data, dict):
            return data
        
        # Filtrar valores None
        filtered_data = {k: v for k, v in data.items() if v is not None}
        return filtered_data

    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:
        # Verificación temprana para evitar procesamiento innecesario
        if value is None:
            return None
            
        model_fields = self.__class__.model_fields
        field_info = model_fields.get(info.field_name)
        metadata = self.__get_custom_metadata(field_info) if field_info else {}

        # Si no hay metadata, devolver el valor sin procesar
        if not metadata:
            return self.__serialize_normal_field(value)

        # --- Caso ID ---
        if metadata.get("id") is True:
            is_root = info.context and info.context.get("is_root", False)
            if is_root:
                return None
            firestore_path = info.context.get("firestore_path") if info.context else None
            if firestore_path:
                return CollectionReference(path=firestore_path)
            return str(value) if isinstance(value, UUID) else value

        # --- Caso reference ---
        if metadata.get("reference") is True:
            return self.__get_document(value, metadata)

        # --- Caso subcollection ---
        if "subcollection" in metadata:
            parent_path = info.context.get("parent_path") if info.context else None
            return self.__serialize_subcollection(
                value, info.field_name, metadata, parent_path
            )

        # Sin metadata especial → serialización normal
        return self.__serialize_normal_field(value)

    def __serialize_normal_field(self, value: Any) -> Any:
        """Serializa campos normales (sin collection) - solo ID string"""
        if isinstance(value, (list, tuple)):
            return [self.__serialize_normal_item(item) for item in value]
        elif isinstance(value, set):
            # Convertir set a list para evitar problemas de hashability
            return [self.__serialize_normal_item(item) for item in value]
        else:
            return self.__serialize_normal_item(value)

    def __serialize_normal_item(self, item: Any) -> Any:
        """Serializa un item normal - solo ID como string"""
        if not hasattr(item, "model_dump"):
            return item
        
        # Para campos normales (sin collection), solo devolver el ID como string
        item_id = getattr(item, "id", None)
        if item_id is not None:
            item_id_str = str(item_id) if isinstance(item_id, UUID) else item_id
            return {"id": item_id_str}
        
        # Si no tiene ID, serializar normalmente
        return item.model_dump()

    def __serialize_subcollection(
        self, value, field_name: str, metadata: dict, parent_path: str = None
    ):
        # nombre explícito o plural automático
        collection_expression = metadata.get("subcollection") or plural(field_name)
        base_path = self.__build_collection_path(collection_expression, parent_path)

        # Manejar diferentes tipos de iterables
        if isinstance(value, set):
            iterable = list(value)
        elif isinstance(value, (list, tuple)):
            iterable = value
        else:
            # Si es un solo item, convertir a lista
            iterable = [value] if value is not None else []
            
        return [
            self.__serialize_subcollection_item(item, base_path, collection_expression)
            for item in iterable
        ]

    def __serialize_subcollection_item(self, item, base_path: str, collection_expression: str):
        if not hasattr(item, "model_dump"):
            return item

        # Obtener el ID del item (siempre existe según las reglas)
        item_id = getattr(item, "id", None)
        if item_id is None:
            raise ValueError(f"El item {item} no tiene ID requerido para collection")
        
        item_id_str = str(item_id) if isinstance(item_id, UUID) else item_id

        # --- Soporte para {id} dinámico ---
        if "{id}" in collection_expression:
            # Reemplazar {id} con el ID del item
            resolved_path = base_path.replace("{id}", item_id_str)
        else:
            # Añadir el ID al final del path
            resolved_path = f"{base_path}/{item_id_str}"

        # Contexto para el item de subcolección
        context = {
            "parent_path": resolved_path,
            "firestore_path": resolved_path
        }

        # Serializar el item con el contexto adecuado
        try:
            return item.model_dump(context=context)
        except Exception as e:
            print(f"Error serializando item {item}: {e}")
            raise

    def __build_collection_path(
        self, collection_expression: str, parent_path: str = None
    ) -> str:
        # Resolver placeholders que NO sean {id} (ese se resuelve en el item)
        import re
        pattern = r"\{([^}]+)\}"
        matches = re.finditer(pattern, collection_expression)

        resolved_expression = collection_expression
        for match in matches:
            attribute_name = match.group(1)
            if attribute_name == "id":
                continue  # Se resuelve en __serialize_subcollection_item
            placeholder = match.group(0)
            attribute_value = self.__get_attribute_value(attribute_name)
            if attribute_value is not None:
                resolved_expression = resolved_expression.replace(
                    placeholder, str(attribute_value)
                )

        base_path = parent_path or self.__get_current_document_path()
        return f"{base_path}/{resolved_expression}" if base_path else resolved_expression

    def __get_current_document_path(self) -> str:
        class_name = plural(self.__class__.__name__.lower())
        doc_id = None
        for field_name, field_info in self.__class__.model_fields.items():
            metadata = self.__get_custom_metadata(field_info)
            if metadata.get("id") is True:
                doc_id = getattr(self, field_name, None)
                break
        if doc_id is not None:
            doc_id_str = str(doc_id) if isinstance(doc_id, UUID) else doc_id
            return f"{class_name}/{doc_id_str}"
        return class_name

    def __get_attribute_value(self, attribute_name: str):
        try:
            return getattr(self, attribute_name, None)
        except:
            return None   

    def __get_custom_metadata(self, field_info: Any) -> dict:
        if not field_info:
            return {}
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
            metadata.get("collection_name") or plural(value.__class__.__name__.lower())
        )
        doc_id = str(value.id) if isinstance(value.id, UUID) else value.id
        return DocumentReference(path=f"{collection_name}/{doc_id}")

    #model_config = ConfigDict(frozen=True)


class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer):
    pass