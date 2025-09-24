from typing import Any, Dict, List, Optional, Set, get_args, get_origin, Union, Type
from pydantic import BaseModel
from common.inflect import plural
from enum import Enum
import inspect
import re

# ==================== CONSTANTS ====================

PLACEHOLDER_PATTERN = re.compile(r"\{([^}]+)\}")


class FieldTypes:
    ID = "id"
    GEOPOINT = "geopoint"
    REFERENCE = "reference"
    COLLECTION = "collection"
    PRIMITIVE = "primitive"
    ENUM = "enum"
    EMBEDDED = "embedded"
    SIMPLE_ARRAY = "simple_array"
    OBJECT_ARRAY = "object_array"
    SET = "set"
    TUPLE = "tuple"
    UNKNOWN = "unknown"


class EntityTypes:
    DOCUMENT = "document"
    EMBEDDABLE = "embeddable"


class Strategies:
    ID_FIELD = "id_field"
    GEOPOINT_VALUE = "geopoint_value"
    REFERENCE_PATH = "reference_path"
    COLLECTION_WITH_PATHS = "collection_with_paths"
    DIRECT = "direct"


class DiffStrategies:
    BY_ID = "by_id"
    ARRAY_OPERATIONS = "array_operations"
    BY_OBJECT_EQUALITY = "by_object_equality"
    SET_COMPARISON = "set_comparison"
    DIRECT_COMPARISON = "direct_comparison"


class MetadataKeys:
    ID = "id"
    GEOPOINT = "geopoint"
    REFERENCE = "reference"
    COLLECTION = "collection"


class SchemaKeys:
    PROPERTIES = "properties"
    ENTITY_METADATA = "entity_metadata"
    TYPE = "type"
    STRATEGY = "strategy"
    REFERENCE_METADATA = "reference_metadata"
    COLLECTION_METADATA = "collection_metadata"
    ARRAY_METADATA = "array_metadata"
    TARGET_ENTITY = "target_entity"
    PATH_RESOLVER = "path_resolver"
    ELEMENT_ENTITY = "element_entity"
    PATH_PATTERN = "path_pattern"
    REFERENCE_field = "reference_field"
    DIFF_STRATEGY = "diff_strategy"
    ELEMENT_TYPE = "element_type"
    ENTITY_NAME = "entity_name"
    ID_FIELD = "id_field"
    COLLECTION_NAME = "collection_name"
    DEPENDENCIES = "dependencies"
    DOCUMENTS = "documents"
    EMBEDDABLES = "embeddables"


class PlaceholderKeys:
    ID = "id"


class FieldCategories:
    SET = "set"
    LIST = "list"
    TUPLE = "tuple"
    PRIMITIVE = "primitive"
    ENUM = "enum"
    EMBEDDED = "embedded"
    UNKNOWN = "unknown"


class ElementTypes:
    MIXED = "mixed"
    UNKNOWN = "unknown"


PRIMITIVE_TYPES = frozenset({str, int, float, bool})
EXCLUDED_METADATA_KEYS = frozenset({"string", "integer", "number", "boolean"})
CONTAINER_TYPES = frozenset({list, set, tuple})

# ==================== SCHEMA BUILDERS (FIXED) ====================


class SchemaBuilder:
    """Factory para construcción de schemas - LIMPIO como Schema.json esperado"""

    @staticmethod
    def build_basic_schema(field_type: str, strategy: str) -> Dict[str, str]:
        return {SchemaKeys.TYPE: field_type, SchemaKeys.STRATEGY: strategy}

    @staticmethod
    def build_reference_schema(
        target_entity: str, path_resolver: str
    ) -> Dict[str, Any]:
        return {
            SchemaKeys.TYPE: FieldTypes.REFERENCE,
            SchemaKeys.STRATEGY: Strategies.REFERENCE_PATH,
            SchemaKeys.DIFF_STRATEGY: DiffStrategies.BY_OBJECT_EQUALITY,  # ← AÑADIR
            SchemaKeys.REFERENCE_METADATA: {
                SchemaKeys.TARGET_ENTITY: target_entity,
                SchemaKeys.PATH_RESOLVER: path_resolver,
            },
        }

    @staticmethod
    def build_collection_schema(
        element_entity: str, path_pattern: str, reference_field: str
    ) -> Dict[str, Any]:
        return {
            SchemaKeys.TYPE: FieldTypes.COLLECTION,
            SchemaKeys.STRATEGY: Strategies.COLLECTION_WITH_PATHS,
            SchemaKeys.DIFF_STRATEGY: DiffStrategies.BY_OBJECT_EQUALITY,  # ← AÑADIR
            SchemaKeys.COLLECTION_METADATA: {
                SchemaKeys.ELEMENT_ENTITY: element_entity,
                SchemaKeys.PATH_PATTERN: path_pattern,
                SchemaKeys.REFERENCE_field: reference_field,
            },
        }

    @staticmethod
    def build_simple_array_schema(field_type: str) -> Dict[str, Any]:
        """✅ FIXED: simple_array con strategy 'direct' y sin array_metadata"""
        return {SchemaKeys.TYPE: field_type, SchemaKeys.STRATEGY: Strategies.DIRECT}

    @staticmethod
    def build_tuple_schema() -> Dict[str, Any]:
        """✅ FIXED: tuple con strategy 'direct' y sin array_metadata"""
        return {
            SchemaKeys.TYPE: FieldTypes.TUPLE,
            SchemaKeys.STRATEGY: Strategies.DIRECT,
        }

    @staticmethod
    def build_complex_array_schema(
        field_type: str, element_type: str, diff_strategy: str
    ) -> Dict[str, Any]:
        """Para object_array y set que NO necesitan metadata"""
        return {
            SchemaKeys.TYPE: field_type,
            SchemaKeys.STRATEGY: Strategies.DIRECT,
            SchemaKeys.DIFF_STRATEGY: diff_strategy,
        }

    @staticmethod
    def build_entity_schema(
        properties: Dict[str, Any], entity_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        return {
            SchemaKeys.PROPERTIES: properties,
            SchemaKeys.ENTITY_METADATA: entity_metadata,
        }


# ==================== FIELD PROCESSORS ====================


class FieldProcessor:
    """Procesador de campos con validaciones robustas"""

    def __init__(self, all_models: Dict[str, Type[BaseModel]]):
        self.all_models = all_models

    def process_reference_field(
        self, field_info, metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Procesa campo reference con validación completa"""
        target_type = self._extract_base_type(field_info.annotation)
        target_entity = target_type.__name__ if target_type else "Unknown"
        collection_name = metadata.get("collection_name")

        if collection_name:
            path_resolver = self._resolve_path_pattern(
                collection_name, target_entity, target_type
            )
        else:
            path_resolver = f"{plural(target_entity.lower())}/{{{target_entity}.{PlaceholderKeys.ID}}}"

        return SchemaBuilder.build_reference_schema(target_entity, path_resolver)

    def process_collection_field(
        self, field_name: str, field_info, metadata: Dict[str, Any], current_entity: str
    ) -> Dict[str, Any]:
        """Procesa campo collection con validación de placeholders"""
        element_type = self._extract_list_element_type(field_info.annotation)
        element_entity = element_type.__name__ if element_type else "Unknown"
        collection_name = metadata.get("collection_name")

        if collection_name:
            self._validate_collection_placeholders(collection_name, element_type)
            path_pattern = self._build_collection_path(
                collection_name, element_entity, element_type, current_entity
            )
            reference_field = self._determine_reference_field(
                PLACEHOLDER_PATTERN.findall(collection_name)
            )
        else:
            path_pattern = f"{plural(current_entity.lower())}/{{{current_entity}.{PlaceholderKeys.ID}}}/{field_name}/{{{element_entity}.{PlaceholderKeys.ID}}}"
            reference_field = PlaceholderKeys.ID

        return SchemaBuilder.build_collection_schema(
            element_entity, path_pattern, reference_field
        )

    def _validate_collection_placeholders(
        self, collection_name: str, element_type: Type
    ):
        """Valida placeholders según si es Document o Embeddable"""
        placeholders = PLACEHOLDER_PATTERN.findall(collection_name)

        for placeholder in placeholders:
            if placeholder == PlaceholderKeys.ID and not self._is_document_type(
                element_type
            ):
                raise ValueError(
                    f"Placeholder '{{{PlaceholderKeys.ID}}}' usado en collection(\"{collection_name}\") "
                    f"pero {element_type.__name__} es Embeddable (sin campo id). "
                    f"Los Embeddables no tienen ID para usar en paths."
                )
            elif placeholder != PlaceholderKeys.ID:
                self._validate_field_exists(placeholder, element_type, collection_name)

    def _validate_field_exists(
        self, placeholder: str, element_type: Type, collection_name: str
    ):
        """Valida que un campo existe en el tipo"""
        if (
            not hasattr(element_type, "model_fields")
            or placeholder not in element_type.model_fields
        ):
            available_fields = (
                list(element_type.model_fields.keys())
                if hasattr(element_type, "model_fields")
                else []
            )
            raise ValueError(
                f"Placeholder '{{{placeholder}}}' en collection(\"{collection_name}\") "
                f"no existe en {element_type.__name__}. "
                f"Campos disponibles: {available_fields}"
            )

    def _build_collection_path(
        self,
        collection_name: str,
        element_entity: str,
        element_type: Type,
        parent_entity: str,
    ) -> str:
        """Construye path de collection con validación"""
        parent_collection = plural(parent_entity.lower())

        if not collection_name.startswith(parent_collection):
            resolved_pattern = self._resolve_path_pattern(
                collection_name, element_entity, element_type
            )
            return f"{parent_collection}/{{{parent_entity}.id}}/{resolved_pattern}"
        else:
            return self._resolve_path_pattern(
                collection_name, element_entity, element_type
            )

    def _resolve_path_pattern(
        self, pattern: str, target_entity: str, target_type: Type
    ) -> str:
        """Resuelve placeholders con validación robusta"""
        if "." in pattern:
            return pattern

        resolved = pattern
        placeholders = PLACEHOLDER_PATTERN.findall(pattern)

        for placeholder in placeholders:
            match placeholder:
                case "id":
                    if not self._is_document_type(target_type):
                        raise ValueError(
                            f"Placeholder '{{id}}' usado para {target_entity} que es Embeddable. "
                            f"Los Embeddables no tienen campo id."
                        )
                    resolved = resolved.replace("{id}", f"{{{target_entity}.id}}")
                case _:
                    self._validate_placeholder_field(
                        placeholder, target_type, target_entity
                    )
                    resolved = resolved.replace(
                        f"{{{placeholder}}}", f"{{{target_entity}.{placeholder}}}"
                    )

        return resolved

    def _validate_placeholder_field(
        self, placeholder: str, target_type: Type, target_entity: str
    ):
        """Valida que un placeholder existe como campo"""
        if (
            not hasattr(target_type, "model_fields")
            or placeholder not in target_type.model_fields
        ):
            available_fields = (
                list(target_type.model_fields.keys())
                if hasattr(target_type, "model_fields")
                else []
            )
            raise ValueError(
                f"Placeholder '{{{placeholder}}}' no existe en {target_entity}. "
                f"Campos disponibles: {available_fields}"
            )

    def _determine_reference_field(self, placeholders: List[str]) -> str:
        """Determina campo de referencia evitando 'id' si no existe"""
        non_id_placeholders = [p for p in placeholders if p != PlaceholderKeys.ID]
        return non_id_placeholders[0] if non_id_placeholders else PlaceholderKeys.ID

    def _is_document_type(self, model_class: Type[BaseModel]) -> bool:
        """Verifica si tiene campo ID (es Document) con búsqueda optimizada"""
        if not hasattr(model_class, "model_fields"):
            return False

        return any(
            self._extract_field_metadata(field_info).get(MetadataKeys.ID, False)
            for field_info in model_class.model_fields.values()
        )

    def _extract_field_metadata(self, field_info) -> Dict[str, Any]:
        """Extrae metadata de FieldInfo"""
        if (
            not hasattr(field_info, "json_schema_extra")
            or not field_info.json_schema_extra
        ):
            return {}
        return field_info.json_schema_extra.get("metadata", {})

    def _extract_base_type(self, annotation):
        """Extrae tipo base manejando Optional"""
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none_types = [arg for arg in args if arg is not type(None)]
            return (
                self._extract_base_type(non_none_types[0])
                if non_none_types
                else annotation
            )
        else:
            return annotation

    def _extract_list_element_type(self, annotation):
        """Extrae tipo de elemento de contenedores"""
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            non_none_args = [arg for arg in args if arg is not type(None)]
            return (
                self._extract_list_element_type(non_none_args[0])
                if non_none_args
                else None
            )
        elif origin in CONTAINER_TYPES:
            args = get_args(annotation)
            return args[0] if args else None
        else:
            return None


# ==================== TYPE ANALYZER (FIXED) ====================


class TypeAnalyzer:
    """Analizador de tipos con pattern matching optimizado - CORREGIDO"""

    @staticmethod
    def detect_field_category(annotation) -> str:
        """Detecta categoría del campo con pattern matching CORREGIDO"""
        origin = get_origin(annotation)

        # Manejar Optional primero
        if origin is Union:
            args = get_args(annotation)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                return TypeAnalyzer.detect_field_category(non_none_args[0])

        # ✅ CORRECCIÓN: Pattern matching con tipos reales, no strings
        match origin:
            case _ if origin is set:
                return FieldCategories.SET
            case _ if origin is list:
                return FieldCategories.LIST
            case _ if origin is tuple:
                return FieldCategories.TUPLE
            case _:
                return TypeAnalyzer._analyze_direct_type(annotation)

    @staticmethod
    def _analyze_direct_type(annotation) -> str:
        """Analiza tipos directos con pattern matching corregido"""
        if annotation in PRIMITIVE_TYPES:
            return FieldCategories.PRIMITIVE
        elif inspect.isclass(annotation) and issubclass(annotation, Enum):
            return FieldCategories.ENUM
        elif TypeAnalyzer.is_pydantic_model(annotation):
            return FieldCategories.EMBEDDED
        else:
            return FieldCategories.UNKNOWN

    @staticmethod
    def is_pydantic_model(type_class) -> bool:
        """Verifica si es modelo Pydantic"""
        return (
            inspect.isclass(type_class)
            and hasattr(type_class, "model_fields")
            and issubclass(type_class, BaseModel)
        )

    @staticmethod
    def get_element_type_name(element_type) -> str:
        """Obtiene nombre del tipo de elemento"""
        if TypeAnalyzer.is_pydantic_model(element_type):
            return element_type.__name__
        elif element_type is not None:
            return element_type.__name__.lower()
        else:
            return ElementTypes.UNKNOWN

    @staticmethod
    def get_set_diff_strategy(element_type) -> str:
        """Estrategia de diff para Set"""
        return (
            DiffStrategies.BY_ID
            if TypeAnalyzer.is_pydantic_model(element_type)
            else DiffStrategies.SET_COMPARISON
        )


# ==================== DEPENDENCY ANALYZER ====================


class DependencyAnalyzer:
    """Analizador de dependencias con clasificación correcta"""

    def __init__(self, all_models: Dict[str, Type[BaseModel]]):
        self.all_models = all_models

    def extract_dependencies(self, properties: Dict[str, Any]) -> Dict[str, List[str]]:
        """Extrae y clasifica dependencias"""
        documents = set()
        embeddables = set()

        for field_props in properties.values():
            target_entities = self._extract_target_entities(field_props)

            for entity_name in target_entities:
                target_model = self.all_models.get(entity_name)

                if target_model:
                    if self._is_document_type(target_model):
                        documents.add(entity_name)
                    else:
                        embeddables.add(entity_name)

        return {
            SchemaKeys.DOCUMENTS: sorted(list(documents)),
            SchemaKeys.EMBEDDABLES: sorted(list(embeddables)),
        }

    def _extract_target_entities(self, field_props: Dict[str, Any]) -> List[str]:
        """Extrae entidades target de un campo"""
        field_type = field_props.get(SchemaKeys.TYPE)

        match field_type:
            case FieldTypes.REFERENCE:
                target = field_props.get(SchemaKeys.REFERENCE_METADATA, {}).get(
                    SchemaKeys.TARGET_ENTITY
                )
                return [target] if target else []

            case FieldTypes.COLLECTION:
                target = field_props.get(SchemaKeys.COLLECTION_METADATA, {}).get(
                    SchemaKeys.ELEMENT_ENTITY
                )
                return [target] if target else []

            case FieldTypes.OBJECT_ARRAY | FieldTypes.SET:
                metadata = field_props.get(SchemaKeys.ARRAY_METADATA, {})
                element_type = metadata.get(SchemaKeys.ELEMENT_TYPE)
                return (
                    [element_type]
                    if element_type and element_type not in EXCLUDED_METADATA_KEYS
                    else []
                )

            case _:
                return []

    def _is_document_type(self, model_class: Type[BaseModel]) -> bool:
        """Verifica si es Document (tiene campo ID)"""
        for field_info in model_class.model_fields.values():
            if (
                not hasattr(field_info, "json_schema_extra")
                or not field_info.json_schema_extra
            ):
                continue
            metadata = field_info.json_schema_extra.get("metadata", {})
            if metadata.get(MetadataKeys.ID):
                return True
        return False


# ==================== MAIN GENERATOR (FIXED) ====================


class DocumentSchemaGenerator:
    """Generador principal con arquitectura limpia - CORREGIDO"""

    def __init__(self):
        self.processed_entities: Set[str] = set()
        self.all_models: Dict[str, Type[BaseModel]] = {}
        self._current_entity: Optional[str] = None
        self._field_processor: Optional[FieldProcessor] = None
        self._dependency_analyzer: Optional[DependencyAnalyzer] = None

    def generate_schema(self, model_class: Type[BaseModel]) -> Dict[str, Any]:
        """Genera esquema flat optimizado"""
        self._initialize_generation(model_class)

        return {
            model_name: self._process_entity_schema(model_cls)
            for model_name, model_cls in self.all_models.items()
            if model_name not in self.processed_entities
        }

    def _initialize_generation(self, model_class: Type[BaseModel]):
        """Inicializa el estado para generación"""
        self._reset_state()
        self._discover_all_models(model_class)
        self._field_processor = FieldProcessor(self.all_models)
        self._dependency_analyzer = DependencyAnalyzer(self.all_models)

    def _reset_state(self):
        """Resetea estado del generador"""
        self.processed_entities.clear()
        self.all_models.clear()
        self._current_entity = None

    def _discover_all_models(
        self, model_class: Type[BaseModel], visited: Optional[Set[str]] = None
    ):
        """Descubrimiento recursivo de modelos"""
        if visited is None:
            visited = set()

        model_name = model_class.__name__
        if model_name in visited:
            return

        visited.add(model_name)
        self.all_models[model_name] = model_class

        # Buscar modelos relacionados
        for field_info in model_class.model_fields.values():
            for related_model in self._extract_related_models(field_info.annotation):
                if TypeAnalyzer.is_pydantic_model(related_model):
                    self._discover_all_models(related_model, visited)

    def _extract_related_models(self, annotation) -> List[Type]:
        """Extrae modelos relacionados"""
        models = []
        origin = get_origin(annotation)

        if origin is Union:
            non_none_args = [
                arg for arg in get_args(annotation) if arg is not type(None)
            ]
            for arg in non_none_args:
                models.extend(self._extract_related_models(arg))
        elif origin in CONTAINER_TYPES:
            args = get_args(annotation)
            if args:
                models.extend(self._extract_related_models(args[0]))
        else:
            if TypeAnalyzer.is_pydantic_model(annotation):
                models.append(annotation)

        return models

    def _process_entity_schema(self, model_class: Type[BaseModel]) -> Dict[str, Any]:
        """Procesa esquema de entidad individual"""
        model_name = model_class.__name__

        if model_name in self.processed_entities:
            return {}

        self.processed_entities.add(model_name)
        self._current_entity = model_name

        # Procesar campos
        properties = {
            field_name: self._process_field_schema(field_name, field_info, model_class)
            for field_name, field_info in model_class.model_fields.items()
        }

        # Generar metadata
        entity_metadata = self._generate_entity_metadata(model_class, properties)

        return SchemaBuilder.build_entity_schema(properties, entity_metadata)

    def _process_field_schema(
        self, field_name: str, field_info, model_class: Type[BaseModel]
    ) -> Dict[str, Any]:
        """Procesa campo individual con pattern matching corregido"""
        metadata = self._extract_field_metadata(field_info)

        if metadata.get(MetadataKeys.ID):
            return SchemaBuilder.build_basic_schema(FieldTypes.ID, Strategies.ID_FIELD)
        elif metadata.get(MetadataKeys.GEOPOINT):
            return SchemaBuilder.build_basic_schema(
                FieldTypes.GEOPOINT, Strategies.GEOPOINT_VALUE
            )
        elif metadata.get(MetadataKeys.REFERENCE):
            return self._field_processor.process_reference_field(field_info, metadata)
        elif metadata.get(MetadataKeys.COLLECTION):
            return self._field_processor.process_collection_field(
                field_name, field_info, metadata, self._current_entity
            )
        else:
            return self._process_regular_field(field_info)

    def _process_regular_field(self, field_info) -> Dict[str, Any]:
        """✅ FIXED: Procesa campos regulares con schemas limpios"""
        annotation = field_info.annotation
        field_category = TypeAnalyzer.detect_field_category(annotation)

        match field_category:
            case FieldCategories.SET:
                return self._build_set_schema(annotation)
            case FieldCategories.LIST:
                return self._build_list_schema(annotation)
            case FieldCategories.TUPLE:
                return (
                    SchemaBuilder.build_tuple_schema()
                )  # ✅ FIXED: Sin array_metadata
            case FieldCategories.PRIMITIVE:
                return SchemaBuilder.build_basic_schema(
                    FieldTypes.PRIMITIVE, Strategies.DIRECT
                )
            case FieldCategories.ENUM:
                return SchemaBuilder.build_basic_schema(
                    FieldTypes.ENUM, Strategies.DIRECT
                )
            case FieldCategories.EMBEDDED:
                return SchemaBuilder.build_basic_schema(
                    FieldTypes.EMBEDDED, Strategies.DIRECT
                )
            case _:
                return SchemaBuilder.build_basic_schema(
                    FieldTypes.UNKNOWN, Strategies.DIRECT
                )

    def _build_set_schema(self, annotation) -> Dict[str, Any]:
        element_type = self._field_processor._extract_list_element_type(annotation)
        element_name = TypeAnalyzer.get_element_type_name(element_type)
    
        return SchemaBuilder.build_complex_array_schema(FieldTypes.SET, element_name, DiffStrategies.BY_OBJECT_EQUALITY)

    def _build_list_schema(self, annotation) -> Dict[str, Any]:
        """✅ FIXED: Schema para List - simple_array limpio, object_array con by_object_equality"""
        element_type = self._field_processor._extract_list_element_type(annotation)
        
        if element_type in PRIMITIVE_TYPES:
            # ✅ FIXED: simple_array con schema limpio (sin array_metadata)
            return SchemaBuilder.build_simple_array_schema(FieldTypes.SIMPLE_ARRAY)
        elif TypeAnalyzer.is_pydantic_model(element_type):
            # ✅ FIXED: object_array con by_object_equality
            return SchemaBuilder.build_complex_array_schema(
                FieldTypes.OBJECT_ARRAY, 
                element_type.__name__, 
                DiffStrategies.BY_OBJECT_EQUALITY
            )
        else:
            return SchemaBuilder.build_simple_array_schema(FieldTypes.SIMPLE_ARRAY)

    def _generate_entity_metadata(
        self, model_class: Type[BaseModel], properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        """✅ FIXED: Genera metadata de entidad - solo incluir dependencies si existen"""
        model_name = model_class.__name__
        id_field = self._find_id_field(properties)
        entity_type = EntityTypes.DOCUMENT if id_field else EntityTypes.EMBEDDABLE

        # Metadata base
        metadata = {SchemaKeys.TYPE: entity_type, SchemaKeys.ENTITY_NAME: model_name}

        # Añadir campos específicos para Document
        if entity_type == EntityTypes.DOCUMENT:
            metadata.update(
                {
                    SchemaKeys.ID_FIELD: id_field,
                    SchemaKeys.COLLECTION_NAME: plural(model_name.lower()),
                }
            )

        # ✅ FIXED: Solo añadir dependencies si realmente existen
        dependencies = self._dependency_analyzer.extract_dependencies(properties)
        if dependencies[SchemaKeys.DOCUMENTS] or dependencies[SchemaKeys.EMBEDDABLES]:
            metadata[SchemaKeys.DEPENDENCIES] = dependencies

        return metadata

    def _find_id_field(self, properties: Dict[str, Any]) -> Optional[str]:
        """Encuentra campo ID"""
        for field_name, field_props in properties.items():
            if field_props.get(SchemaKeys.TYPE) == FieldTypes.ID:
                return field_name
        return None

    def _extract_field_metadata(self, field_info) -> Dict[str, Any]:
        """Extrae metadata de FieldInfo"""
        if (
            not hasattr(field_info, "json_schema_extra")
            or not field_info.json_schema_extra
        ):
            return {}
        return field_info.json_schema_extra.get("metadata", {})


# ==================== HELPER FUNCTION ====================


def generate_flat_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """Función helper optimizada"""
    generator = DocumentSchemaGenerator()
    return generator.generate_schema(model_class)
