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


# ===== MIXIN SERIALIZER REFACTORIZADO V2 =====


class MixinSerializer(BaseModel):
    """
    Serializer optimizado con ownership tracking.
    
    Mejoras V2:
    1. Sistema de Ownership tracking via context
    2. Diferenciación entre owned collections y referenced entities
    3. Serialización correcta de Sets de Documents
    4. Propagación correcta del schema a entidades anidadas
    5. Soporte para reference_field personalizado en collections
    
    Context estructura:
    {
        "schema": Dict,              # Schema completo del aggregate root
        "ownership_path": List[str], # Stack: ["Store", "Product"]
        "current_entity": str,       # Entidad siendo serializada
        "is_collection_item": bool,  # Si está dentro de una collection owned
        "parent_path_resolver": str, # Path pattern del parent
        "parent_instance": obj,      # Instancia del parent para resolver placeholders
        "current_item": obj,         # Item actual para resolver placeholders
        "reference_field": str       # Campo que actúa como referencia de colección
    }
    """

    def model_dump_aggregate_root(self, mode: str = "python") -> Dict[str, Any]:
        """
        Serializa usando el schema de la entidad root con @entity decorator.
        
        Args:
            mode: Modo de serialización ('json' o 'python')
            
        Returns:
            Dict serializado usando estrategias del schema
            
        Raises:
            ValueError: Si la clase no tiene @entity decorator
        """
        if not hasattr(self.__class__, "__document_schema__"):
            raise ValueError(
                f"Class {self.__class__.__name__} debe usar @entity decorator "
                f"para usar model_dump_aggregate_root(). "
                f"Use model_dump() normal para objetos sin decorator."
            )
        
        schema = self.__class__.__document_schema__
        context = {
            "schema": schema,
            "ownership_path": [self.__class__.__name__],
            "current_entity": self.__class__.__name__,
            "is_collection_item": False,
            "parent_path_resolver": None,
            "parent_instance": None,
            "current_item": None,
            "reference_field": "id"
        }
        
        return self.model_dump(mode=mode, context=context)

    @field_serializer("*")
    def _serialize(self, value: Any, info: FieldSerializationInfo) -> Any:
        """Serialización basada en schema strategies con ownership tracking"""
        
        # Preservar None explícitos
        if value is None:
            return None
        
        field_name = info.field_name
        
        # NUEVO: Detectar si este campo es el reference_field de una collection
        # Esto debe hacerse ANTES de obtener el field_schema
        if info.context and info.context.get("is_collection_item", False):
            reference_field = info.context.get("reference_field", "id")
            if field_name == reference_field:
                # Este campo actúa como referencia de colección
                return self._serialize_collection_reference_field(value, info)
        
        field_schema = self._get_field_schema(field_name, info.context)
        
        if not field_schema:
            return self._serialize_normal_field(value, info)
        
        strategy = field_schema.get("strategy", "direct")
        
        # Manejar collections/sets ANTES de las estrategias individuales
        if isinstance(value, (list, set, tuple)) and strategy not in ["direct", "geopoint_value"]:
            return self._serialize_collection_or_set(value, field_schema, info)
        
        # Estrategias para campos individuales
        match strategy:
            case "id_field":
                return self._serialize_id_field(value, info)
            case "geopoint_value":
                return self._serialize_geopoint(value)
            case "reference_path":
                return self._serialize_reference(value, field_schema)
            case "collection_with_paths":
                return self._serialize_owned_collection(value, field_schema, info)
            case "direct" | _:
                return self._serialize_normal_field(value, info)

    # ==================== FIELD SCHEMA ====================

    def _get_field_schema(
        self, field_name: str, context: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Obtiene schema del campo desde context.
        
        Busca en la entidad actual usando current_entity del context.
        """
        if not context or "schema" not in context:
            return {}
        
        schema = context["schema"]
        current_entity = context.get("current_entity")
        
        if not current_entity or current_entity not in schema:
            return {}
        
        entity_schema = schema[current_entity]
        if "properties" not in entity_schema:
            return {}
        
        return entity_schema["properties"].get(field_name, {})

    # ==================== COLLECTION / SET SERIALIZERS ====================

    def _serialize_collection_or_set(
        self, value: Any, field_schema: Dict[str, Any], info: FieldSerializationInfo
    ) -> List[Any]:
        """
        Serializa collections/sets distinguiendo entre:
        - Owned collections (del aggregate root) → serializar con paths
        - Sets de Documents (no owned) → serializar completo
        - Arrays simples → serializar directo
        """
        strategy = field_schema.get("strategy", "direct")
        
        if strategy == "collection_with_paths":
            # Es una collection owned del aggregate root
            return self._serialize_owned_collection(value, field_schema, info)
        elif strategy == "direct" and self._is_document_set(value):
            # Es un Set de Documents NO owned (como tags en Product)
            return self._serialize_document_set(value, info)
        else:
            # Array simple (strings, numbers, etc.)
            return self._serialize_normal_field(value, info)

    def _serialize_owned_collection(
        self, value: Any, field_schema: Dict[str, Any], info: FieldSerializationInfo
    ) -> List[Dict]:
        """
        Serializa collections owned por el aggregate root.
        
        Ejemplo 1 - reference_field='id':
        products: List[Product] = collection()
        → El campo 'id' se serializa como CollectionReference
        
        Ejemplo 2 - reference_field='name':
        categories: List[Category] = collection("categories/{name}")
        → El campo 'name' se serializa como CollectionReference
        → El campo 'id' se serializa como UUID simple
        """
        if not value:
            return []
        
        collection_metadata = field_schema.get("collection_metadata", {})
        path_pattern = collection_metadata.get("path_pattern", "")
        reference_field = collection_metadata.get("reference_field", "id")
        element_entity = collection_metadata.get("element_entity")
        
        result = []
        items = list(value) if isinstance(value, set) else value
        
        for item in items:
            if not hasattr(item, "model_fields"):
                # Item primitivo
                result.append(item)
                continue
            
            # Crear context para el item owned
            item_context = self._create_child_context(
                parent_context=info.context,
                entity_name=element_entity or item.__class__.__name__,
                is_collection_item=True,
                path_pattern=path_pattern,
                current_item=item,
                reference_field=reference_field
            )
            
            # Serializar el item COMPLETO usando su propio serializer
            # El campo indicado en reference_field se serializará como CollectionReference
            item_data = item.model_dump(context=item_context)
            
            result.append(item_data)
        
        return result

    def _serialize_document_set(
        self, value: Any, info: FieldSerializationInfo
    ) -> List[Dict]:
        """
        Serializa Sets de Documents que NO son collections del aggregate root.
        
        Ejemplo: tags: Set[Tag] en Product
        - Serializa cada Document COMPLETO
        - NO propaga el context del aggregate root (cada Tag es independiente)
        """
        if not value:
            return []
        
        result = []
        items = list(value) if isinstance(value, set) else value
        
        for item in items:
            if not hasattr(item, "model_fields"):
                result.append(item)
                continue
            
            # Serializar el Document completo SIN context del aggregate
            # Esto hace que el id se serialice como DocumentId normal
            item_data = item.model_dump()
            
            result.append(item_data)
        
        return result

    # ==================== INDIVIDUAL FIELD SERIALIZERS ====================

    def _serialize_collection_reference_field(
        self, value: Any, info: FieldSerializationInfo
    ) -> CollectionReference:
        """
        Serializa un campo que actúa como referencia de colección.
        
        Este método se ejecuta cuando:
        - is_collection_item=True
        - field_name == reference_field
        
        Ejemplo:
        categories: List[Category] = collection("categories/{name}")
        → reference_field = "name"
        → El campo 'name' se serializa como CollectionReference
        """
        path_pattern = info.context.get("parent_path_resolver", "")
        
        if not path_pattern:
            # Fallback: si no hay path_pattern, retornar el valor como string
            return str(value)
        
        resolved_path = self._resolve_collection_field_path(
            path_pattern,
            value,
            info.field_name,
            info.context
        )
        
        return CollectionReference(path=resolved_path)

    def _serialize_id_field(
        self, value: Any, info: FieldSerializationInfo
    ) -> Union[DocumentId, CollectionReference, str]:
        """
        Serializa el campo 'id' como DocumentId, CollectionReference o UUID según el contexto.
        
        Lógica:
        1. Si is_collection_item=True Y reference_field=='id' → CollectionReference
        2. Si is_collection_item=True Y reference_field!='id' → UUID simple (otro campo es la referencia)
        3. Si es root document → DocumentId
        4. Otherwise → string
        """
        if not info.context:
            return str(value)
        
        schema = info.context.get("schema", {})
        current_entity = info.context.get("current_entity")
        is_collection_item = info.context.get("is_collection_item", False)
        reference_field = info.context.get("reference_field", "id")
        
        if not current_entity or current_entity not in schema:
            return str(value)
        
        entity_metadata = schema[current_entity].get("entity_metadata", {})
        
        # Caso 1: Es item de una collection owned
        if is_collection_item:
            # Si reference_field es 'id', entonces 'id' se serializa como CollectionReference
            if reference_field == "id":
                path_pattern = info.context.get("parent_path_resolver", "")
                if path_pattern:
                    resolved_path = self._resolve_collection_field_path(
                        path_pattern, 
                        value,
                        "id",
                        info.context
                    )
                    return CollectionReference(path=resolved_path)
            else:
                # Si reference_field != 'id', entonces 'id' se serializa como UUID simple
                # porque otro campo (como 'name') es la referencia
                return str(value)
        
        # Caso 2: Root document o document independiente
        if entity_metadata.get("type") == "document" and entity_metadata.get("collection_name"):
            collection_name = entity_metadata["collection_name"]
            return DocumentId(path=f"{collection_name}/{str(value)}")
        
        return str(value)

    def _serialize_reference(
        self, value: Any, field_schema: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """
        Serializa reference retornando SOLO el path.
        
        Ejemplo: category en Product
        Input:  Category(id=123, name="Electronics", ...)
        Output: {"path": "categories/123"}
        """
        if value is None:
            return None
        
        reference_metadata = field_schema.get("reference_metadata", {})
        path_resolver = reference_metadata.get("path_resolver", "")
        
        # Resolver path usando placeholders
        resolved_path = self._resolve_path_placeholders(path_resolver, value)
        
        # Retornar SOLO el path (no más campos del objeto referenciado)
        return {"path": resolved_path}

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
                longitude=float(value["longitude"])
            )
        elif isinstance(value, GeoPointValue):
            return value
        else:
            raise ValueError(
                f"GeoPoint debe ser tuple(lat, lng), dict con 'latitude'/'longitude', "
                f"o GeoPointValue. Recibido: {type(value)} = {value}"
            )

    def _serialize_normal_field(self, value: Any, info: FieldSerializationInfo) -> Any:
        """Serializa campos normales sin metadata especial"""
        if isinstance(value, (list, tuple, set)):
            return self._serialize_iterable_field(value)
        else:
            return self._serialize_single_item(value)

    # ==================== PATH RESOLVERS ====================

    def _resolve_collection_field_path(
        self, path_pattern: str, field_value: Any, field_name: str, context: Dict
    ) -> str:
        """
        Resuelve el path completo para un campo de collection (puede ser 'id' o 'name').
        
        Soporta dos formatos de placeholders:
        1. Con entidad: {EntityName.field} → "stores/{Store.id}/products/{Product.id}"
        2. Sin entidad: {field} → "categories/{name}"
        
        Ejemplos:
        
        Caso 1 - reference_field='id':
        Pattern: "stores/{Store.id}/products/{Product.id}"
        Context: ownership_path=["Store", "Product"], field_value=UUID("abc-123")
        Result:  "stores/def-456/products/abc-123"
        
        Caso 2 - reference_field='name':
        Pattern: "categories/{name}"
        Context: current_entity="Category", field_value="Electronics"
        Result:  "categories/Electronics"
        """
        resolved = path_pattern
        
        ownership_path = context.get("ownership_path", [])
        current_entity = context.get("current_entity")
        parent_instance = context.get("parent_instance")
        current_item = context.get("current_item")
        
        # Paso 1: Resolver placeholders CON entidad {EntityName.field}
        pattern_with_entity = re.compile(r"\{([^.]+)\.([^}]+)\}")
        
        def replace_with_entity(match):
            entity_name = match.group(1)
            placeholder_field = match.group(2)
            
            # Caso 1: Es el root entity (Store)
            if entity_name == ownership_path[0]:
                if parent_instance and hasattr(parent_instance, placeholder_field):
                    value = getattr(parent_instance, placeholder_field)
                    return str(value)
            
            # Caso 2: Es la entidad actual (Product, Category, etc.)
            elif entity_name == current_entity:
                # Si el placeholder coincide con el field actual, usar field_value
                if placeholder_field == field_name:
                    return str(field_value)
                # Sino, obtener del current_item
                elif current_item and hasattr(current_item, placeholder_field):
                    value = getattr(current_item, placeholder_field)
                    return str(value)
            
            return match.group(0)  # No reemplazar si no encontramos
        
        resolved = pattern_with_entity.sub(replace_with_entity, resolved)
        
        # Paso 2: Resolver placeholders SIN entidad {field}
        # Estos asumen la entidad actual y usan current_item o field_value
        pattern_without_entity = re.compile(r"\{([^.}]+)\}")
        
        def replace_without_entity(match):
            placeholder_field = match.group(1)
            
            # Si el placeholder coincide con el field actual, usar field_value directamente
            if placeholder_field == field_name:
                return str(field_value)
            
            # Para otros campos, obtener del current_item
            if current_item and hasattr(current_item, placeholder_field):
                value = getattr(current_item, placeholder_field)
                return str(value)
            
            # No pudimos resolver
            return match.group(0)
        
        resolved = pattern_without_entity.sub(replace_without_entity, resolved)
        
        return resolved

    def _resolve_path_placeholders(
        self, path_pattern: str, referenced_item: Any
    ) -> str:
        """
        Resuelve placeholders en reference paths.
        
        Ejemplo:
        Pattern: "categories/{Category.id}"
        Item:    Category(id=123, ...)
        Result:  "categories/123"
        """
        if not path_pattern:
            return ""
        
        resolved = path_pattern
        
        # Pattern: {EntityName.field}
        placeholder_pattern = re.compile(r"\{([^.]+)\.([^}]+)\}")
        
        def replace_placeholder(match):
            entity_name = match.group(1)
            field_name = match.group(2)
            
            # El valor viene del objeto referenciado
            if hasattr(referenced_item, field_name):
                field_value = getattr(referenced_item, field_name)
                return str(field_value)
            
            return match.group(0)
        
        resolved = placeholder_pattern.sub(replace_placeholder, resolved)
        return resolved

    # ==================== CONTEXT HELPERS ====================

    def _create_child_context(
        self,
        parent_context: Dict,
        entity_name: str,
        is_collection_item: bool,
        path_pattern: Optional[str] = None,
        current_item: Optional[Any] = None,
        reference_field: str = "id"
    ) -> Dict:
        """
        Crea un context para serializar entidades hijas.
        
        Propaga:
        - schema completo
        - ownership_path actualizado
        - información de collection_item
        - path_pattern para resolver IDs
        - referencia al parent para resolver placeholders
        - current_item para resolver placeholders sin entidad
        - reference_field para indicar qué campo es la referencia de colección
        """
        ownership_path = parent_context.get("ownership_path", []).copy()
        ownership_path.append(entity_name)
        
        return {
            "schema": parent_context.get("schema"),
            "ownership_path": ownership_path,
            "current_entity": entity_name,
            "is_collection_item": is_collection_item,
            "parent_path_resolver": path_pattern,
            "parent_instance": self,  # Para resolver {Store.id} en placeholders
            "current_item": current_item,
            "reference_field": reference_field
        }

    # ==================== TYPE CHECKERS ====================

    def _is_document_set(self, value: Any) -> bool:
        """
        Verifica si un iterable es un Set de Documents.
        
        Criterios:
        - Es list/set/tuple
        - Los items tienen model_fields (son Pydantic models)
        - Los items tienen atributo 'id' (son Documents)
        """
        if not isinstance(value, (list, set, tuple)) or not value:
            return False
        
        first_item = next(iter(value))
        
        return (
            hasattr(first_item, "model_fields") and 
            hasattr(first_item, "id")
        )

    # ==================== ITERABLE HELPERS ====================

    def _serialize_iterable_field(self, value: Any) -> List[Any]:
        """Serializa campos iterables normales (arrays simples)"""
        if isinstance(value, set):
            iterable = list(value)
        else:
            iterable = value
        
        return [self._serialize_single_item(item) for item in iterable]

    def _serialize_single_item(self, item: Any) -> Any:
        """Serializa un item individual"""
        if not hasattr(item, "__dict__"):
            return item
        
        # Para objetos con model_fields pero sin schema (@entity)
        if hasattr(item, "model_fields"):
            return item.model_dump()
        
        return item


# ===== CLASES PRINCIPALES =====


class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer):
    model_config = ConfigDict(frozen=True, extra="forbid")