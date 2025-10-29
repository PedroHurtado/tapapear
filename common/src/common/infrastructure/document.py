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
    model_config = ConfigDict(frozen=True, extra="forbid")

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

    # En MixinSerializer
    def model_dumnp_aggregate_root(self, mode: str = "python") -> Dict[str, Any]:
        """
        Serializa usando el schema de la entidad root con @entity decorator.

        Args:
            mode: Modo de serialización ('json' por defecto)

        Returns:
            Dict serializado usando estrategias del schema

        Raises:
            ValueError: Si la clase no tiene @entity decorator
        """
        # Validar que tiene @entity decorator
        if not hasattr(self.__class__, "__document_schema__"):
            raise ValueError(
                f"Class {self.__class__.__name__} debe usar @entity decorator "
                f"para usar model_dump_entity(). Use model_dump() normal para objetos sin decorator."
            )

        # Obtener schema y pasarlo via context
        schema = self.__class__.__document_schema__
        context = {"schema": schema,"source_fields":{}}

        # Delegar a model_dump con context
        return self.model_dump(mode=mode, context=context)

    @field_serializer("*")
    def _serialize(self, value: Any, info: FieldSerializationInfo) -> Any:
        """Serialización basada en schema strategies"""

        # TODO: remove de la source_fields el source
        # por source-class igual a class.name

       
        # Preservar None explícitos
        if value is None:
            return None
        
        field_name = info.field_name

        field_schema = self._get_field_schema(field_name, info.context)
        if not field_schema:
            return self._serialize_normal_field(value)
        strategy = field_schema.get("strategy", "direct")


        if isinstance(value, (list, set, tuple)) and info.context:
            # Para cada item en la colección, pasar el context
            # crear un source_fiels con el field_schema
            # calcular la ruta hasta donde yo sea propietario
            """
            {
            'source-class':'Products',
            'target_class': Tag,
            'metadata':{
                    "type": "reference",
                    "strategy": "reference_path",
                    "diff_strategy": "by_object_equality",
                    "reference_metadata": {
                    "target_entity": "Category",
                    "path_resolver": "categories/{Category.id}"
                    }
            }            
            """
            return [
                (
                    item.model_dump(context=info.context)
                    if isinstance(item, BaseModel)
                    else item
                )
                for item in value
            ]

        
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

    def _get_field_schema(
        self, field_name: str, context: dict = None
    ) -> Dict[str, Any]:
        """Obtiene schema del campo desde context del @aggregate_root"""

        # Solo buscar en el context
        if not context or "schema" not in context:
            return {}

        parent_schema = context["schema"]
        entity_name = self.__class__.__name__

        # Buscar mi entidad en el schema del aggregate root
        if entity_name not in parent_schema:
            return {}

        entity_schema = parent_schema[entity_name]
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
        """Serializa campos ID según schema del aggregate root"""
        schema = info.context["schema"]
        class_name = self.__class__.__name__

        if not info.context or not schema or class_name not in schema:
            return str(value)

        entity_metadata = schema[class_name].get("entity_metadata", {})

        if entity_metadata.get("type") == "document" and entity_metadata.get(
            "collection_name"
        ):
            collection_name = entity_metadata["collection_name"]
            return DocumentId(path=f"{collection_name}/{str(value)}")

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
    model_config = ConfigDict(frozen=True, extra="forbid")
