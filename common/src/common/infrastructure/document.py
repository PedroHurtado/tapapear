from uuid import UUID
from typing import (
    Any,
    Annotated,
    get_args,
    get_origin,
    Union,
    Tuple,
    List,
    Dict,
    Callable,
    Optional,
)
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
import re


# Constante para placeholders
PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")


def id():
    return Field(metadata={"id": True}, default_factory=lambda: get_id())


def reference(collection_name: str = None):
    return Field(metadata={"reference": True, "collection_name": collection_name})


def collection(collection_name: str = None):
    return Field(metadata={"collection": True, "collection_name": collection_name})


def geopoint():
    """Campo para coordenadas geográficas que se serializan como GeoPointValue"""
    return Field(metadata={"geopoint": True})


# ===== CLASES BASE =====


class BaseReference(BaseModel):
    """Clase base para todas las referencias con serialización común"""

    path: str
    model_config = ConfigDict(frozen=True, extra='forbid')

    @model_serializer(mode="wrap")
    def _serialize_model(
        self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo
    ):
        data = serializer(self)
        if info.mode == "json":
            return data
        else:
            return self.__class__(**data)


class DocumentId(BaseReference):
    """ID de documento root - solo contiene el ID"""

    pass


class DocumentReference(BaseReference):
    """Referencia a un documento - path completo de la referencia"""

    pass


class CollectionReference(BaseReference):
    """Referencia a una colección - path completo de la colección"""

    pass


class GeoPointValue(BaseModel):
    latitude: float
    longitude: float
    model_config = ConfigDict(frozen=True)

    @model_serializer(mode="wrap")
    def _serialize_model(
        self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo
    ):
        data = serializer(self)
        if info.mode == "json":
            return data
        else:
            return GeoPointValue(**data)


# ===== MIXIN SERIALIZER REFACTORIZADO =====


class MixinSerializer(BaseModel):
    """
    Serializer optimizado usando schema generado por @entity decorator.

    Elimina cache manual y resolvers, usa schema como single source of truth.
    Solo para Document y Embeddable classes.
    """

    def _serialize_value(self,value):
        if isinstance(value, BaseModel):        
            return value.model_dump(mode="json")
        elif isinstance(value, (list,set,tuple)):
            return [self._serialize_value(i) for i in value]
        else:
            return value

    """
    @model_serializer(mode="wrap")
    def _serialize_model(
        self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo
    ):
        
        data = {}
        for k in self.__class__.model_fields:
            value = getattr(self, k)
            data[k] = self._serialize_value(value)
        return data
    """
    @field_serializer("*")
    def _serialize(self, value: Any, info: FieldSerializationInfo) -> Any:
        """Serialización basada en schema strategies"""
        # Preservar None explícitos        
        print(f"Serializando {info.field_name}:")

        if value is None:
            return None

        field_name = info.field_name

        # Solo usar schema si es root document con @entity
        field_schema = self._get_field_schema(field_name)
        if not field_schema:
            return self._serialize_normal_field(value)

        # Serializar según strategy del schema
        strategy = field_schema.get("strategy", "direct")

        match strategy:
            case "id_field":
                return self._serialize_id_field(value, info)
            case "geopoint_value":
                return self._serialize_geopoint(value)
            case "reference_path":
                return self._serialize_reference(value, field_schema)
            case "collection_with_paths":
                return self._serialize_collection(value, field_schema)
            case "direct_array":
                return self._serialize_array(value, field_schema)
            case "direct" | _:
                return self._serialize_normal_field(value)

    def _get_field_schema(self, field_name: str) -> Dict[str, Any]:
        """Obtiene schema del campo desde @entity decorator"""
        # Solo funciona si tiene __document_schema__ (root document con @entity)
        if not hasattr(self.__class__, "__document_schema__"):
            return {}

        schema = self.__class__.__document_schema__
        entity_name = self.__class__.__name__

        # Verificar estructura del schema
        if entity_name not in schema:
            return {}

        entity_schema = schema[entity_name]
        if "properties" not in entity_schema:
            return {}

        return entity_schema["properties"].get(field_name, {})

    def _get_entity_metadata(self) -> Dict[str, Any]:
        """Obtiene metadata de la entidad desde schema"""
        if not hasattr(self.__class__, "__document_schema__"):
            return {}

        try:
            schema = self.__class__.__document_schema__
            entity_name = self.__class__.__name__
            return schema[entity_name]["entity_metadata"]
        except (KeyError, AttributeError):
            return {}

    # ==================== FIELD SERIALIZERS ====================

    def _serialize_id_field(
        self, value: Any, info: FieldSerializationInfo
    ) -> Union[DocumentId, CollectionReference, str]:
        """Serializa campos ID según contexto"""
        document_path = info.context.get("document_path") if info.context else None

        if document_path:
            # Subcollection → CollectionReference
            return CollectionReference(path=document_path)
        elif info.context is None and self._is_root_document():
            # Root document → DocumentId con collection/uuid
            entity_metadata = self._get_entity_metadata()
            collection_name = entity_metadata.get("collection_name", "unknown")
            return DocumentId(path=f"{collection_name}/{str(value)}")
        else:
            # Objeto anidado → String directo
            return str(value)

    def _serialize_geopoint(self, value: Any) -> Optional[GeoPointValue]:
        """Serializa geopoint según diferentes formatos"""
        if value is None:
            return None

        if isinstance(value, (tuple, list)) and len(value) == 2:
            latitude, longitude = value
            return GeoPointValue(latitude=float(latitude), longitude=float(longitude))
        elif isinstance(value, dict) and "latitude" in value and "longitude" in value:
            return GeoPointValue(
                latitude=float(value["latitude"]),
                longitude=float(value["longitude"]),
            )
        elif isinstance(value, GeoPointValue):
            return value
        else:
            raise ValueError(
                f"GeoPoint debe ser tuple(lat, lng), dict con 'latitude'/'longitude', o GeoPointValue. "
                f"Recibido: {type(value)} = {value}"
            )

    def _serialize_reference(
        self, value: Any, field_schema: Dict[str, Any]
    ) -> Dict[str, str]:
        """Serializa reference usando path_resolver del schema"""
        if value is None:
            return None

        reference_metadata = field_schema.get("reference_metadata", {})
        path_resolver = reference_metadata.get("path_resolver", "")

        # Resolver path usando placeholders
        resolved_path = self._resolve_path_placeholders(path_resolver, value)

        return {"path": resolved_path}

    def _serialize_collection(
        self, value: Any, field_schema: Dict[str, Any]
    ) -> Optional[List[dict]]:
        """Serializa collection usando schema metadata"""
        if value is None:
            return None

        if not value:  # Lista vacía
            return []

        collection_metadata = field_schema.get("collection_metadata", {})
        path_pattern = collection_metadata.get("path_pattern", "")
        reference_field = collection_metadata.get("reference_field", "id")

        result = []
        items = list(value) if isinstance(value, set) else value

        for item in items:
            if not hasattr(item, "__dict__"):
                result.append(item)
                continue

            # Serialización manual del item
            item_data = self._manual_serialize_item(item)

            # Resolver path del item
            item_path = self._resolve_collection_path(path_pattern, item)
            item_data[reference_field] = CollectionReference(path=item_path)

            result.append(item_data)

        return result

    def _serialize_array(self, value: Any, field_schema: Dict[str, Any]) -> Any:
        """Serializa arrays según array_metadata"""
        if isinstance(value, (list, tuple, set)):
            return self._serialize_iterable_field(value)
        else:
            return self._serialize_single_item(value)

    # ==================== PATH RESOLVERS ====================

    def _resolve_path_placeholders(
        self, path_pattern: str, referenced_item: Any
    ) -> str:
        """Resuelve placeholders en reference paths"""
        if not path_pattern:
            return ""

        resolved = path_pattern

        # Pattern: "categories/{Category.id}" → "categories/123"
        placeholder_pattern = re.compile(r"\{([^.]+)\.([^}]+)\}")

        def replace_placeholder(match):
            entity_name = match.group(1)
            field_name = match.group(2)

            # El valor viene del objeto referenciado
            field_value = getattr(referenced_item, field_name, "")
            return str(field_value)

        resolved = placeholder_pattern.sub(replace_placeholder, resolved)

        return resolved

    def _resolve_collection_path(self, path_pattern: str, item: Any) -> str:
        """Resuelve path completo para item de collection"""
        if not path_pattern:
            return ""

        resolved = path_pattern

        # Pattern: "stores/{Store.id}/products/{Product.id}"
        placeholder_pattern = re.compile(r"\{([^.]+)\.([^}]+)\}")

        def replace_placeholder(match):
            entity_name = match.group(1)
            field_name = match.group(2)

            # Si es el entity del item actual, usar su valor
            if entity_name == item.__class__.__name__:
                field_value = getattr(item, field_name, "")
                return str(field_value)
            # Si es el entity padre (Store), usar valor de self
            elif entity_name == self.__class__.__name__:
                field_value = getattr(self, field_name, "")
                return str(field_value)
            else:
                return match.group(0)  # No reemplazar si no encontramos

        resolved = placeholder_pattern.sub(replace_placeholder, resolved)

        return resolved

    # ==================== HELPER METHODS ====================

    def _manual_serialize_item(self, item: Any) -> dict:
        """Serialización manual preservando None values"""
        if not hasattr(item, "model_fields"):
            return item.__dict__.copy() if hasattr(item, "__dict__") else item

        result = {}

        # Si el item tiene schema (@entity), usar su serializer
        if hasattr(item.__class__, "__document_schema__"):
            # Usar el serializer del item
            return item.model_dump()

        # Fallback a serialización manual
        for field_name, field_info in item.__class__.model_fields.items():
            value = getattr(item, field_name, None)

            if value is None:
                result[field_name] = None
                continue

            # Serializar según tipo
            if isinstance(value, (list, set, tuple)):
                if not value:
                    result[field_name] = []
                else:
                    result[field_name] = [
                        (
                            self._manual_serialize_item(x)
                            if hasattr(x, "model_fields")
                            else x
                        )
                        for x in value
                    ]
            elif hasattr(value, "model_fields"):
                result[field_name] = self._manual_serialize_item(value)
            else:
                result[field_name] = value

        return result

    def _serialize_normal_field(self, value: Any) -> Any:
        """Serializa campos normales sin metadata especial"""
        if isinstance(value, (list, tuple, set)):
            return self._serialize_iterable_field(value)
        else:
            return self._serialize_single_item(value)

    def _serialize_iterable_field(self, value: Any) -> List[Any]:
        """Serializa campos iterables normales"""
        if isinstance(value, set):
            iterable = list(value)
        else:
            iterable = value

        return [self._serialize_single_item(item) for item in iterable]

    def _serialize_single_item(self, item: Any) -> Any:
        """Serializa un item individual"""
        if not hasattr(item, "__dict__"):
            return item

        # Para objetos Document con schema, usar su serializer
        if hasattr(item, "model_fields"):
            if hasattr(item.__class__, "__document_schema__"):
                return item.model_dump()
            else:
                return self._manual_serialize_item(item)

        return item

    def _is_root_document(self) -> bool:
        """Verifica si es root document (tiene @entity decorator)"""
        return hasattr(self.__class__, "__document_schema__")


# ===== CLASES PRINCIPALES =====


class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer):
    model_config = ConfigDict(frozen=True, extra='forbid')
