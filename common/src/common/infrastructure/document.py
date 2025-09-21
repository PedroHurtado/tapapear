from uuid import UUID
from typing import Any, Annotated, get_args, get_origin, Union, Tuple, List, Dict, Callable, Optional
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
    model_config = ConfigDict(frozen=True)

    @model_serializer(mode="wrap")
    def __serialize_model__(
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
    def __serialize_model__(
        self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo
    ):
        data = serializer(self)
        if info.mode == "json":
            return data
        else:
            return GeoPointValue(**data)


# ===== MIXIN SERIALIZER =====


class MixinSerializer(BaseModel):
    # Cache estático por clase con nombres dunder - SOLO campos especiales
    __metadata_cache__: Dict[str, Dict] = {}
    __path_resolvers__: Dict[str, Callable] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        """Validación + Cache + Resolvers en una sola pasada"""
        cls._build_metadata_cache_and_resolvers()

    @classmethod
    def _build_metadata_cache_and_resolvers(cls):
        """Construye cache y resolvers en tiempo de compilación - SOLO campos especiales"""
        cls.__metadata_cache__ = {}
        cls.__path_resolvers__ = {}
        
        for field_name, field_info in cls.model_fields.items():
            metadata = cls._extract_metadata(field_info)
            
            # ✅ OPTIMIZACIÓN - Solo cachear campos con metadata útil
            if metadata:  # Solo si no está vacío
                cls.__metadata_cache__[field_name] = metadata
                
                # Crear resolver específico según tipo
                if metadata.get("collection"):
                    cls._validate_collection_field(field_name, field_info, metadata)
                    cls.__path_resolvers__[field_name] = cls._create_collection_resolver(
                        field_name, metadata
                    )
                elif metadata.get("reference"):
                    cls._validate_reference_field(field_name, field_info, metadata)
                    cls.__path_resolvers__[field_name] = cls._create_reference_resolver(
                        field_name, metadata
                    )

    @classmethod
    def _create_collection_resolver(cls, field_name: str, metadata: dict) -> Callable:
        """Crea resolver optimizado para collection fields"""
        collection_pattern = metadata.get("collection_name")
        
        if collection_pattern is None:
            # collection() - usar field_name + id
            def resolve_path(self, item):
                base = self._get_base_path()
                return f"{base}/{field_name}/{item.id}"
            resolve_path.reference_field = "id"
            return resolve_path
        
        elif "{" not in collection_pattern:
            # collection("fixed_name") - nombre fijo + id  
            def resolve_path(self, item):
                base = self._get_base_path()
                return f"{base}/{collection_pattern}/{item.id}"
            resolve_path.reference_field = "id"
            return resolve_path
        
        else:
            # collection("path/{placeholder}") - resolver dinámicamente
            placeholders = PLACEHOLDER_PATTERN.findall(collection_pattern)
            reference_field = next((p for p in placeholders if p != "id"), "id")
            
            def resolve_path(self, item):
                base = self._get_base_path()
                resolved = collection_pattern
                for placeholder in placeholders:
                    if placeholder == "id":
                        resolved = resolved.replace("{id}", str(item.id))
                    else:
                        value = getattr(item, placeholder, "")
                        resolved = resolved.replace(f"{{{placeholder}}}", str(value))
                return f"{base}/{resolved}"
            
            resolve_path.reference_field = reference_field
            return resolve_path

    @classmethod  
    def _create_reference_resolver(cls, field_name: str, metadata: dict) -> Callable:
        """Crea resolver optimizado para reference fields - TODAS las variantes"""
        collection_pattern = metadata.get("collection_name")
        
        if collection_pattern is None:
            # reference() - inferir del tipo del objeto referenciado
            def resolve_path(self, referenced_item):
                return f"{plural(referenced_item.__class__.__name__.lower())}/{referenced_item.id}"
            return resolve_path
        
        elif "{" not in collection_pattern:
            # reference("fixed_collection") - nombre fijo + id del referenciado
            def resolve_path(self, referenced_item):
                return f"{collection_pattern}/{referenced_item.id}"
            return resolve_path
        
        else:
            # reference("collection/{field}") - resolver placeholders desde self + id del referenciado
            def resolve_path(self, referenced_item):
                resolved = collection_pattern
                
                # Resolver placeholders usando valores de self (objeto padre)
                placeholders = PLACEHOLDER_PATTERN.findall(collection_pattern)
                for placeholder in placeholders:
                    if placeholder == "id":
                        # {id} se refiere al ID del objeto referenciado
                        resolved = resolved.replace("{id}", str(referenced_item.id))
                    else:
                        # Otros placeholders se buscan en self (objeto padre)
                        attr_value = getattr(self, placeholder, None)
                        if attr_value is not None:
                            resolved = resolved.replace(f"{{{placeholder}}}", str(attr_value))
                
                # Si no había {id} en el pattern, agregarlo al final
                if "{id}" not in collection_pattern:
                    resolved = f"{resolved}/{referenced_item.id}"
                
                return resolved
            return resolve_path

    @classmethod
    def _validate_collection_field(cls, field_name: str, field_info, metadata: dict):
        """Valida configuración de campos collection"""
        # Obtener tipo del elemento (manejando Optional)
        element_type = cls._get_list_element_type(field_info)
        if not element_type:
            raise ValueError(
                f"Campo '{field_name}' debe ser List[T] o Optional[List[T]] para usar collection()"
            )

        collection_name = metadata.get("collection_name")

        if collection_name is None:
            # collection() sin parámetro - debe tener 'id'
            cls._validate_field_exists(element_type, "id", field_name, "collection()")
        else:
            # collection("path") o collection("path/{attr}")
            placeholders = PLACEHOLDER_PATTERN.findall(collection_name)

            if placeholders:
                # Tiene placeholders - validar cada uno
                for placeholder in placeholders:
                    cls._validate_field_exists(
                        element_type,
                        placeholder,
                        field_name,
                        f'collection("{collection_name}")',
                    )
            else:
                # Sin placeholders - debe tener 'id'
                cls._validate_field_exists(
                    element_type,
                    "id",
                    field_name,
                    f'collection("{collection_name}")',
                )

    @classmethod
    def _validate_reference_field(cls, field_name: str, field_info, metadata: dict):
        """Valida configuración de campos reference"""
        collection_name = metadata.get("collection_name")

        if collection_name:
            # reference("path/{attr}") - validar placeholders
            placeholders = PLACEHOLDER_PATTERN.findall(collection_name)

            # Los placeholders en reference se buscan en la clase actual, no en el tipo referenciado
            for placeholder in placeholders:
                if not hasattr(cls, placeholder):
                    raise ValueError(
                        f"Campo '{field_name}' usa placeholder '{{{placeholder}}}' en reference(\"{collection_name}\"), "
                        f"pero {cls.__name__} no tiene atributo '{placeholder}'"
                    )

    @classmethod
    def _validate_field_exists(
        cls, target_type, field_name: str, source_field: str, source_config: str
    ):
        """Valida que un campo existe en el tipo destino"""
        if (
            not hasattr(target_type, "model_fields")
            or field_name not in target_type.model_fields
        ):
            raise ValueError(
                f"Campo '{source_field}' usa {source_config}, "
                f"pero {target_type.__name__} no tiene campo '{field_name}'"
            )

    @classmethod
    def _get_list_element_type(cls, field_info):
        """Extrae el tipo de elemento de List[T] o Optional[List[T]]"""
        try:
            field_annotation = field_info.annotation

            # Manejar Union (Optional)
            if get_origin(field_annotation) is Union:
                args = get_args(field_annotation)
                # Buscar el tipo que no sea NoneType
                for arg in args:
                    if arg is not type(None) and get_origin(arg) in (list, List):
                        return get_args(arg)[0] if get_args(arg) else None

            # Manejar List directo
            if get_origin(field_annotation) in (list, List):
                args = get_args(field_annotation)
                return args[0] if args else None

            return None
        except Exception:
            return None

    @classmethod
    def _extract_metadata(cls, field_info) -> dict:
        """Extrae metadata de un FieldInfo"""
        if not field_info:
            return {}

        # Buscar en json_schema_extra primero
        if hasattr(field_info, "json_schema_extra") and field_info.json_schema_extra:
            metadata = field_info.json_schema_extra.get("metadata", {})
            if metadata:
                return metadata

        # Buscar en default si es Annotated
        default = getattr(field_info, "default", None)
        if get_origin(default) is Annotated:
            for arg in get_args(default):
                if isinstance(arg, FieldInfo) and hasattr(arg, "json_schema_extra"):
                    if arg.json_schema_extra:
                        return arg.json_schema_extra.get("metadata", {})

        return {}

    @classmethod
    def _has_collection_fields(cls) -> bool:
        """Verifica si la clase tiene algún campo collection"""
        # ✅ OPTIMIZACIÓN - Usar cache en lugar de recorrer todo
        for metadata in cls.__metadata_cache__.values():
            if metadata.get("collection"):
                return True
        return False

    @model_serializer(mode="wrap")
    def __serialize_model__(self, serializer: SerializerFunctionWrapHandler):
        """Serialización sin filtrar None - preserva valores explícitos"""
        data = serializer(self)
        if not isinstance(data, dict):
            return data
        
        # ✅ NO filtrar None - preservar para ChangeTracker
        return data

    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:
        # Verificación temprana - PRESERVAR None explícitos
        if value is None:
            return None

        field_name = info.field_name
        
        # 🚀 CACHE HIT - Solo campos especiales están en cache
        metadata = self.__class__.__metadata_cache__.get(field_name)
        
        if not metadata:
            return self._serialize_normal_field(value)

        # 🚀 RESOLVER DIRECTO - Sin pattern matching
        if metadata.get("id"):
            return self._serialize_id_optimized(value, info)
        
        elif metadata.get("reference"):
            # Manejar Optional[Document] = None ya verificado arriba
            resolver = self.__class__.__path_resolvers__[field_name]
            path = resolver(self, value)
            return {"path": path}
        
        elif metadata.get("geopoint"):
            return self._serialize_geopoint_optimized(value)
        
        elif metadata.get("collection"):
            return self._serialize_collection_optimized(value, field_name)
        
        return self._serialize_normal_field(value)

    def _serialize_id_optimized(
        self, value: Any, info: FieldSerializationInfo
    ) -> Union[DocumentId, CollectionReference, str]:
        """Maneja la serialización de campos ID optimizada"""
        document_path = info.context.get("document_path") if info.context else None

        if document_path:
            # Estamos en subcollection → CollectionReference con path completo
            return CollectionReference(path=document_path)
        elif info.context is None and self._is_root_document():
            # Estamos en ROOT → DocumentId solo con el ID
            # Estamos en ROOT → DocumentId con collection/uuid
            collection_name = plural(self.__class__.__name__.lower())
            return DocumentId(path=f"{collection_name}/{str(value)}")  # ✅ stores/uuid
        else:
            # Estamos en objeto normal anidado → String directo
            return str(value)

    def _is_root_document(self) -> bool:
        """Verifica si este documento es el root (no está anidado)"""
        return self._has_collection_fields()

    def _serialize_geopoint_optimized(self, value: Any) -> Optional[GeoPointValue]:
        """Maneja la serialización de campos geopoint optimizada"""
        if value is None:
            return None

        # Manejar diferentes formatos de entrada
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

    def _serialize_collection_optimized(self, value: Any, field_name: str) -> Optional[List[dict]]:
        """Serialización de collections SIN model_dump, preservando None"""
        # Manejar Optional[List[T]] = None
        if value is None:
            return None
        
        if not value:  # Lista vacía
            return []
        
        resolver = self.__class__.__path_resolvers__[field_name]
        reference_field = getattr(resolver, 'reference_field', 'id')
        
        result = []
        items = list(value) if isinstance(value, set) else value
        
        for item in items:
            if not hasattr(item, '__dict__'):
                result.append(item)
                continue
            
            # 🚀 SERIALIZACIÓN MANUAL - Sin model_dump, preservando None
            item_data = self._manual_serialize_item(item)
            
            # 🚀 RESOLVER DIRECTO - Path optimizado
            item_path = resolver(self, item)
            item_data[reference_field] = CollectionReference(path=item_path)  # ✅ Tipo correcto
            
            result.append(item_data)
        
        return result

    def _manual_serialize_item(self, item: Any) -> dict:
        """Serialización manual preservando None values y usando resolvers"""
        if not hasattr(item, 'model_fields'):
            return item.__dict__.copy()
        
        result = {}
        for field_name, field_info in item.__class__.model_fields.items():
            value = getattr(item, field_name, None)
            
            # 🔥 PRESERVAR None - No excluir nunca
            if value is None:
                result[field_name] = None
                continue
            
            # 🚀 USAR RESOLVERS del item para campos especiales
            item_metadata = item.__class__.__metadata_cache__.get(field_name)
            
            if item_metadata:
                # Campo especial - usar el sistema de serialización
                if item_metadata.get("reference") and value is not None:
                    resolver = item.__class__.__path_resolvers__[field_name]
                    # ✅ CORRECCIÓN: Los placeholders en reference se resuelven desde el objeto padre (item), no desde el referenciado (value)
                    path = resolver(item, value)
                    result[field_name] = {"path": path}
                elif item_metadata.get("geopoint"):
                    result[field_name] = item._serialize_geopoint_optimized(value)
                elif item_metadata.get("id"):
                    result[field_name] = str(value)  # IDs siempre como string en nested
                else:
                    result[field_name] = value
            else:
                # Campo normal
                if isinstance(value, (list, set, tuple)):
                    if not value:  # Colección vacía
                        result[field_name] = []
                    else:
                        result[field_name] = [
                            self._manual_serialize_item(x) if hasattr(x, 'model_fields') else x 
                            for x in value
                        ]
                elif hasattr(value, 'model_fields'):
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

        # Para objetos Document, usar serialización manual preservando None
        if hasattr(item, "model_fields"):
            return self._manual_serialize_item(item)

        return item

    def _get_base_path(self) -> str:
        """Obtiene el path base del documento actual"""
        class_name = plural(self.__class__.__name__.lower())

        # ✅ OPTIMIZACIÓN - Buscar campo ID en cache optimizado
        for field_name, metadata in self.__class__.__metadata_cache__.items():
            if metadata.get("id") is True:
                doc_id = getattr(self, field_name, None)
                if doc_id is not None:
                    return f"{class_name}/{str(doc_id)}"
                break

        return class_name

    def _resolve_placeholders_from_self(self, pattern: str) -> str:
        """Resuelve placeholders usando valores de self"""
        resolved = pattern
        placeholders = PLACEHOLDER_PATTERN.findall(pattern)
        
        for placeholder in placeholders:
            if placeholder == "id":
                # ✅ OPTIMIZACIÓN - Buscar campo ID en cache
                for field_name, metadata in self.__class__.__metadata_cache__.items():
                    if metadata.get("id") is True:
                        doc_id = getattr(self, field_name, None)
                        if doc_id is not None:
                            resolved = resolved.replace("{id}", str(doc_id))
                        break
            else:
                attr_value = getattr(self, placeholder, None)
                if attr_value is not None:
                    resolved = resolved.replace(f"{{{placeholder}}}", str(attr_value))
        
        return resolved


# ===== CLASES PRINCIPALES =====


class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer):
    pass