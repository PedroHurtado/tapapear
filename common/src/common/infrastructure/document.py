from uuid import UUID
from typing import Any, Annotated, get_args, get_origin, Union, Tuple, List
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
    def __serialize_model(
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
    def __serialize_model(
        self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo
    ):
        data = serializer(self)
        if info.mode == "json":
            return data
        else:
            return GeoPointValue(**data)


# ===== MIXIN SERIALIZER =====


class MixinSerializer(BaseModel):

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        """Validación COMPLETA en tiempo de compilación usando hook de Pydantic"""
        cls._validate_all_fields()

    @classmethod
    def _validate_all_fields(cls):
        """Valida TODOS los fields con metadata especial"""
        for field_name, field_info in cls.model_fields.items():
            metadata = cls._extract_metadata(field_info)

            if "collection" in metadata:
                cls._validate_collection_field(field_name, field_info, metadata)
            elif "reference" in metadata:
                cls._validate_reference_field(field_name, field_info, metadata)

    @classmethod
    def _validate_collection_field(cls, field_name: str, field_info, metadata: dict):
        """Valida configuración de campos collection"""
        # Obtener tipo del elemento
        element_type = cls._get_list_element_type(field_info)
        if not element_type:
            raise ValueError(
                f"Campo '{field_name}' debe ser List[T] para usar collection()"
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
        """Extrae el tipo de elemento de List[T]"""
        try:
            field_annotation = field_info.annotation

            if hasattr(field_annotation, "__origin__") and hasattr(
                field_annotation, "__args__"
            ):
                origin = field_annotation.__origin__
                args = field_annotation.__args__

                if origin in (list, List, set, tuple) and args:
                    return args[0]

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
        for field_info in cls.model_fields.values():
            metadata = cls._extract_metadata(field_info)
            if "collection" in metadata:
                return True
        return False

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
        # Verificación temprana
        if value is None:
            return None

        field_info = self.__class__.model_fields.get(info.field_name)
        metadata = self._extract_metadata(field_info) if field_info else {}

        # Sin metadata, serialización normal
        if not metadata:
            return self._serialize_normal_field(value)

        # Pattern matching para diferentes tipos de metadata
        match metadata:
            case {"id": True}:
                return self._serialize_id_field(value, info)

            case {"reference": True}:
                return self._serialize_reference_field(value, metadata)

            case {"geopoint": True}:
                return self._serialize_geopoint_field(value)

            case {"collection": True}:
                return self._serialize_subcollection_field(
                    value, info.field_name, metadata, info
                )

            case _:
                return self._serialize_normal_field(value)

    def _serialize_id_field(
        self, value: Any, info: FieldSerializationInfo
    ) -> Union[DocumentId, CollectionReference, str]:
        """Maneja la serialización de campos ID"""
        document_path = info.context.get("document_path") if info.context else None

        if document_path:
            # Estamos en subcollection → CollectionReference con path completo
            return CollectionReference(path=document_path)
        elif info.context is None and self._is_root_document():
            # Estamos en ROOT → DocumentId solo con el ID
            return DocumentId(path=str(value))
        else:
            # Estamos en objeto normal anidado → String directo
            return str(value)

    def _is_root_document(self) -> bool:
        """Verifica si este documento es el root (no está anidado)"""
        # Un documento es root si tiene collections propias
        return self._has_collection_fields()

    def _serialize_reference_field(
        self, value: Any, metadata: dict
    ) -> DocumentReference:
        """Maneja la serialización de campos reference"""
        if not isinstance(value, Document):
            raise ValueError(
                f"El valor de referencia debe ser una instancia de Document, recibido: {type(value)}"
            )

        # Obtener nombre de colección
        collection_pattern = metadata.get("collection_name")
        if collection_pattern is None:
            # Inferir automáticamente del tipo
            collection_pattern = plural(value.__class__.__name__.lower())

        # Resolver path con placeholders
        resolved_path = self._resolve_path_placeholders(collection_pattern, value)

        return DocumentReference(path=resolved_path)

    def _serialize_geopoint_field(self, value: Any) -> GeoPointValue:
        """Maneja la serialización de campos geopoint"""
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

    def _serialize_subcollection_field(
        self,
        value: Any,
        field_name: str,
        metadata: dict,
        info: FieldSerializationInfo,
    ) -> List[dict]:
        """Serializa campos collection - sin validaciones, solo serialización"""
        parent_path = info.context.get("parent_path") if info.context else None

        # Obtener patrón (ya validado en __init_subclass__)
        collection_pattern = metadata.get("collection_name")
        if collection_pattern is None:
            # Sin patrón específico - usar nombre del field
            collection_pattern = field_name

        # 🔧 FIX: Construir path base correctamente
        base_collection_path = self._build_collection_path(
            collection_pattern, parent_path
        )

        # Convertir a lista
        if isinstance(value, set):
            iterable = list(value)
        elif isinstance(value, (list, tuple)):
            iterable = value
        else:
            iterable = [value] if value is not None else []

        # Serializar cada item
        result = []
        for item in iterable:
            if not hasattr(item, "model_dump"):
                result.append(item)
                continue

            # Determinar campo a convertir (ya validado)
            reference_field = self._get_collection_reference_field(collection_pattern)

            # 🔧 FIX: Serializar item con path correcto
            serialized_item = self._serialize_collection_item_with_reference(
                item, base_collection_path, collection_pattern, reference_field
            )
            result.append(serialized_item)

        return result

    def _get_collection_reference_field(self, collection_pattern: str) -> str:
        """🔧 FIX: Determina qué campo convertir a CollectionReference"""
        placeholders = PLACEHOLDER_PATTERN.findall(collection_pattern)

        # Si hay placeholders, usar el primero que NO sea 'id'
        for placeholder in placeholders:
            if placeholder != "id":
                return placeholder

        # Si no hay placeholders o solo hay {id}, usar 'id'
        return "id"

    def _serialize_collection_item_with_reference(
        self, item: Any, base_path: str, pattern: str, reference_field: str
    ) -> dict:
        """🔧 FIX: Serializa item convirtiendo campo específico a CollectionReference"""

        # 🔧 FIX: Resolver path del item individual
        item_path = self._resolve_item_path_fixed(pattern, item, base_path)

        # Serializar item
        item_data = item.model_dump(mode="json", exclude_none=True)

        # Convertir campo a CollectionReference
        item_data[reference_field] = CollectionReference(path=item_path).model_dump(
            mode="json"
        )

        return item_data

    def _resolve_item_path_fixed(self, pattern: str, item: Any, base_path: str) -> str:
        """🔧 NUEVO: Resuelve path para item individual correctamente"""

        # Si el patrón no tiene placeholders, es el path directo
        if "{" not in pattern:
            # pattern es simplemente el nombre de la colección (ej: "products")
            # El ID del item se agrega al final
            item_id = getattr(item, "id", None)
            if item_id:
                return f"{base_path}/{str(item_id)}"
            else:
                return base_path

        # Si tiene placeholders, resolverlos con valores del item
        resolved_pattern = pattern
        placeholders = PLACEHOLDER_PATTERN.findall(pattern)

        for placeholder in placeholders:
            if placeholder == "id":
                # Placeholder {id} se refiere al ID del item
                item_id = getattr(item, "id", None)
                if item_id:
                    resolved_pattern = resolved_pattern.replace("{id}", str(item_id))
            else:
                # 🔧 FIX: Otros placeholders se buscan en el item, NO en self
                attr_value = getattr(item, placeholder, None)
                if attr_value is not None:
                    resolved_pattern = resolved_pattern.replace(
                        f"{{{placeholder}}}", str(attr_value)
                    )

        # 🔧 FIX: Construir path completo con base_path + pattern resuelto
        # El base_path ya contiene "stores/UUID/categories"
        # El resolved_pattern será "Electronics" (después de resolver {name})
        return f"{base_path}/{resolved_pattern}"

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

        # Para objetos Document, serializar completamente SIN contexto
        # y SIN pasar por nuestro serializer personalizado
        if hasattr(item, "model_dump"):
            # Usar mode='json' sin context para que Pydantic maneje todo normalmente
            return item.model_dump(mode="json", exclude_none=True)

        # Si no tiene ID, devolver tal cual (para compatibilidad)
        return item

    def _infer_collection_name_from_field_type(self, field_name: str) -> str:
        """Infiere el nombre de colección desde el tipo List[T]"""
        try:
            field_info = self.__class__.model_fields.get(field_name)
            if not field_info:
                return plural(field_name)

            # Obtener tipo de la anotación
            field_annotation = field_info.annotation

            # Manejar List[T], Set[T], etc.
            if hasattr(field_annotation, "__origin__") and hasattr(
                field_annotation, "__args__"
            ):
                origin = field_annotation.__origin__
                args = field_annotation.__args__

                if origin in (list, List, set, tuple) and args:
                    element_type = args[0]
                    if hasattr(element_type, "__name__"):
                        return plural(element_type.__name__.lower())

            # Fallback
            return plural(field_name)

        except Exception:
            return plural(field_name)

    def _resolve_path_placeholders(
        self, pattern: str, target_object: Any = None
    ) -> str:
        """Resuelve placeholders en patrones de path - sin validaciones"""
        # Agregar ID si no hay placeholders
        if target_object and "{id}" not in pattern:
            target_id = str(target_object.id)
            pattern = f"{pattern}/{target_id}"
        elif "{id}" in pattern and target_object:
            target_id = str(target_object.id)
            pattern = pattern.replace("{id}", target_id)

        # Resolver otros placeholders desde self
        placeholders = PLACEHOLDER_PATTERN.findall(pattern)
        for placeholder in placeholders:
            if placeholder == "id":
                continue

            attr_value = getattr(self, placeholder, None)
            if attr_value is not None:
                pattern = pattern.replace(f"{{{placeholder}}}", str(attr_value))

        return pattern

    def _build_collection_path(
        self, collection_pattern: str, parent_path: str = None
    ) -> str:
        """🔧 FIX: Construye path de colección correctamente"""

        # Si tenemos parent_path, usarlo como base
        if parent_path:
            base_path = parent_path
        else:
            # Construir path del documento actual
            class_name = plural(self.__class__.__name__.lower())
            doc_id = None

            # Buscar campo ID
            for field_name, field_info in self.__class__.model_fields.items():
                metadata = self._extract_metadata(field_info)
                if metadata.get("id") is True:
                    doc_id = getattr(self, field_name, None)
                    break

            base_path = f"{class_name}/{str(doc_id)}" if doc_id else class_name

        # 🔧 FIX: NO resolver placeholders aquí - se resuelven por item individual
        # Solo extraer el nombre base de la colección (antes del primer placeholder)
        if "{" in collection_pattern:
            # Extraer solo la parte antes del primer placeholder
            base_collection_name = collection_pattern.split("{")[0].rstrip("/")
        else:
            base_collection_name = collection_pattern

        return f"{base_path}/{base_collection_name}"

    def _resolve_pattern_placeholders(self, pattern: str) -> str:
        """🔧 NUEVO: Resuelve placeholders solo en el patrón, no afecta al path base"""
        resolved_pattern = pattern
        placeholders = PLACEHOLDER_PATTERN.findall(pattern)

        # Reemplazar placeholders con valores de self
        for placeholder in placeholders:
            attr_value = getattr(self, placeholder, None)
            if attr_value is not None:
                resolved_pattern = resolved_pattern.replace(
                    f"{{{placeholder}}}", str(attr_value)
                )

        return resolved_pattern

    def _get_current_document_path(self) -> str:
        """Obtiene el path del documento actual"""
        class_name = plural(self.__class__.__name__.lower())

        # Buscar campo ID
        for field_name, field_info in self.__class__.model_fields.items():
            metadata = self._extract_metadata(field_info)
            if metadata.get("id") is True:
                doc_id = getattr(self, field_name, None)
                if doc_id is not None:
                    return f"{class_name}/{str(doc_id)}"
                break

        return class_name


# ===== CLASES PRINCIPALES =====


class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer):
    pass