from typing import Any, Dict, List, Optional, Set, get_args, get_origin, Union, Type
from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema
from enum import Enum
import inspect
import re


class DocumentSchemaGenerator:
    """
    Generador que analiza un modelo Pydantic y genera un esquema
    completamente customizado en formato flat para optimización.
    """
    
    def __init__(self):
        self.processed_entities: Set[str] = set()
        self.all_models: Dict[str, Type[BaseModel]] = {}
        self._current_entity: Optional[str] = None
    
    def generate_schema(self, model_class: Type[BaseModel]) -> Dict[str, Any]:
        """Genera esquema flat optimizado desde cero"""
        # Resetear estado
        self.processed_entities.clear()
        self.all_models.clear()
        
        # Encontrar todos los modelos relacionados
        self._discover_all_models(model_class)
        
        # Generar esquema flat
        flat_schema = {}
        
        for model_name, model_cls in self.all_models.items():
            if model_name not in self.processed_entities:
                flat_schema[model_name] = self._process_entity_schema(model_cls)
        
        return flat_schema
    
    def _discover_all_models(self, model_class: Type[BaseModel], visited: Optional[Set] = None):
        """Descubre recursivamente todos los modelos relacionados"""
        if visited is None:
            visited = set()
        
        model_name = model_class.__name__
        
        if model_name in visited:
            return
        
        visited.add(model_name)
        self.all_models[model_name] = model_class
        
        # Analizar campos para encontrar modelos relacionados
        for field_name, field_info in model_class.model_fields.items():
            related_models = self._extract_related_models(field_info.annotation)
            
            for related_model in related_models:
                if inspect.isclass(related_model) and hasattr(related_model, 'model_fields') and issubclass(related_model, BaseModel):
                    self._discover_all_models(related_model, visited)
    
    def _extract_related_models(self, annotation) -> List[Type]:
        """Extrae tipos de modelos relacionados de una anotación de tipo"""
        models = []
        
        # Manejar Union (Optional)
        if get_origin(annotation) is Union:
            for arg in get_args(annotation):
                if arg is not type(None):
                    models.extend(self._extract_related_models(arg))
        
        # Manejar List, Set, etc.
        elif hasattr(annotation, '__origin__') and get_origin(annotation) in (list, set, tuple):
            args = get_args(annotation)
            if args:
                models.extend(self._extract_related_models(args[0]))
        
        # Modelo directo
        elif (inspect.isclass(annotation) and 
              hasattr(annotation, 'model_fields') and 
              issubclass(annotation, BaseModel)):
            models.append(annotation)
        
        return models
    
    def _process_entity_schema(self, model_class: Type[BaseModel]) -> Dict:
        """Procesa esquema de una entidad individual"""
        model_name = model_class.__name__
        
        if model_name in self.processed_entities:
            return {}
        
        self.processed_entities.add(model_name)
        
        # Guardar entidad actual para uso en path resolution
        self._current_entity = model_name
        
        properties = {}
        
        # Procesar cada campo
        for field_name, field_info in model_class.model_fields.items():
            properties[field_name] = self._process_field_schema(
                field_name, field_info, model_class
            )
        
        # Generar entity_metadata
        entity_metadata = self._generate_entity_metadata(model_class, properties)
        
        return {
            "properties": properties,
            "entity_metadata": entity_metadata
        }
    
    def _process_field_schema(self, field_name: str, field_info, model_class: Type[BaseModel]) -> Dict:
        """Procesa esquema de un campo individual"""
        
        # Extraer metadata si existe
        metadata = self._extract_field_metadata(field_info)
        
        if metadata.get('id'):
            return {
                "type": "id",
                "strategy": "id_field"
            }
        
        elif metadata.get('geopoint'):
            return {
                "type": "geopoint",
                "strategy": "geopoint_value"
            }
        
        elif metadata.get('reference'):
            return self._process_reference_field(field_info, metadata)
        
        elif metadata.get('collection'):
            return self._process_collection_field(field_name, field_info, metadata)
        
        else:
            return self._process_regular_field(field_info)
    
    def _extract_field_metadata(self, field_info) -> Dict:
        """Extrae metadata de un FieldInfo"""
        if not hasattr(field_info, 'json_schema_extra') or not field_info.json_schema_extra:
            return {}
        
        return field_info.json_schema_extra.get('metadata', {})
    
    def _process_reference_field(self, field_info, metadata: Dict) -> Dict:
        """Procesa campo reference"""
        # Extraer tipo target
        annotation = field_info.annotation
        target_type = self._extract_base_type(annotation)
        target_entity = target_type.__name__ if target_type else 'Unknown'
        
        collection_name = metadata.get('collection_name')
        
        if collection_name:
            path_resolver = self._resolve_path_pattern(collection_name, target_entity)
        else:
            # Inferir del nombre de la entidad con pluralización correcta
            path_resolver = f"{self._pluralize(target_entity.lower())}/{{{target_entity}.id}}"
        
        return {
            "type": "reference",
            "strategy": "reference_path",
            "reference_metadata": {
                "target_entity": target_entity,
                "path_resolver": path_resolver
            }
        }
    
    def _process_collection_field(self, field_name: str, field_info, metadata: Dict) -> Dict:
        """Procesa campo collection"""
        # Extraer tipo de elemento
        annotation = field_info.annotation
        element_type = self._extract_list_element_type(annotation)
        element_entity = element_type.__name__ if element_type else 'Unknown'
        
        collection_name = metadata.get('collection_name')
        
        if collection_name:
            # Patrón específico con dot notation y path completo
            parent_entity = self._get_current_entity_name()
            if not collection_name.startswith(self._pluralize(parent_entity.lower())):
                # Añadir path del padre si no está presente
                path_pattern = f"{self._pluralize(parent_entity.lower())}/{{{parent_entity}.id}}/{self._resolve_path_pattern(collection_name, element_entity)}"
            else:
                path_pattern = self._resolve_path_pattern(collection_name, element_entity)
            
            placeholders = re.findall(r'\{([^}]+)\}', collection_name)
            reference_field = next((p.split('.')[-1] for p in placeholders if p != 'id' and '.' in p), 'id')
            if reference_field == 'id':
                reference_field = next((p for p in placeholders if p != 'id'), 'id')
        else:
            # Patrón por defecto usando nombre del field con dot notation
            parent_entity = self._get_current_entity_name()
            path_pattern = f"{self._pluralize(parent_entity.lower())}/{{{parent_entity}.id}}/{field_name}/{{{element_entity}.id}}"
            reference_field = "id"
        
        return {
            "type": "collection",
            "strategy": "collection_with_paths",
            "collection_metadata": {
                "element_entity": element_entity,
                "path_pattern": path_pattern,
                "reference_field": reference_field,
                "diff_strategy": "by_id"
            }
        }
    
    def _process_regular_field(self, field_info) -> Dict:
        """Procesa campos regulares"""
        annotation = field_info.annotation
        
        # PRIMERO verificar si es array/collection antes que el tipo base
        if self._is_set_type(annotation):
            return self._process_set_field(annotation)
        
        elif self._is_list_type(annotation):
            return self._process_list_field(annotation)
        
        elif self._is_tuple_type(annotation):
            return self._process_tuple_field(annotation)
        
        # DESPUÉS extraer tipo base para primitivos
        base_type = self._extract_base_type(annotation)
        
        if base_type == str:
            return {
                "type": "primitive",
                "strategy": "direct"
            }
        
        elif base_type in [int, float, bool]:
            return {
                "type": "primitive", 
                "strategy": "direct"
            }
        
        elif inspect.isclass(base_type) and issubclass(base_type, Enum):
            return {
                "type": "enum",
                "strategy": "direct"
            }
        
        elif inspect.isclass(base_type) and hasattr(base_type, 'model_fields') and issubclass(base_type, BaseModel):
            return {
                "type": "embedded",
                "strategy": "direct"
            }
        
        else:
            return {
                "type": "unknown",
                "strategy": "direct"
            }
    
    def _process_list_field(self, annotation) -> Dict:
        """Procesa campos List"""
        element_type = self._extract_list_element_type(annotation)
        
        if element_type in [str, int, float, bool]:
            return {
                "type": "simple_array",
                "strategy": "direct_array",
                "array_metadata": {
                    "element_type": element_type.__name__.lower(),
                    "diff_strategy": "array_operations"
                }
            }
        elif inspect.isclass(element_type) and hasattr(element_type, 'model_fields') and issubclass(element_type, BaseModel):
            return {
                "type": "object_array",
                "strategy": "direct_array",
                "array_metadata": {
                    "element_type": element_type.__name__,
                    "diff_strategy": "by_id"
                }
            }
        else:
            return {
                "type": "simple_array",
                "strategy": "direct_array"
            }
    
    def _process_set_field(self, annotation) -> Dict:
        """Procesa campos Set"""
        element_type = self._extract_list_element_type(annotation)  # Set usa misma lógica
        
        if inspect.isclass(element_type) and hasattr(element_type, 'model_fields') and issubclass(element_type, BaseModel):
            return {
                "type": "set",
                "strategy": "direct_array",
                "array_metadata": {
                    "element_type": element_type.__name__,
                    "diff_strategy": "set_comparison"
                }
            }
        else:
            return {
                "type": "set",
                "strategy": "direct_array",
                "array_metadata": {
                    "element_type": element_type.__name__.lower() if element_type else "unknown",
                    "diff_strategy": "set_comparison"
                }
            }
    
    def _process_tuple_field(self, annotation) -> Dict:
        """Procesa campos Tuple"""
        return {
            "type": "tuple",
            "strategy": "direct",
            "array_metadata": {
                "element_type": "mixed",
                "diff_strategy": "direct_comparison"
            }
        }
    
    def _generate_entity_metadata(self, model_class: Type[BaseModel], properties: Dict) -> Dict:
        """Genera metadata de la entidad"""
        model_name = model_class.__name__
        
        # Determinar si es Document (buscar campo id)
        id_field = None
        for field_name, field_props in properties.items():
            if field_props.get('type') == 'id':
                id_field = field_name
                break
        
        is_document = id_field is not None
        
        # Encontrar campos especiales
        collection_fields = []
        geopoint_fields = []
        
        for field_name, field_props in properties.items():
            if field_props.get('type') == 'collection':
                collection_fields.append(field_name)
            elif field_props.get('type') == 'geopoint':
                geopoint_fields.append(field_name)
        
        has_collections = len(collection_fields) > 0
        
        # Inferir nombre de colección con pluralización correcta
        collection_name = self._pluralize(model_name.lower()) if is_document else None
        
        # Extraer dependencias
        dependencies = self._extract_dependencies(properties)
        
        # Construir metadata
        metadata = {
            "is_document": is_document,
            "has_collections": has_collections,
            "entity_name": model_name
        }
        
        if id_field:
            metadata["id_field"] = id_field
        
        if collection_name:
            metadata["collection_name"] = collection_name
        
        if collection_fields:
            metadata["collection_fields"] = collection_fields
        
        if geopoint_fields:
            metadata["geopoint_fields"] = geopoint_fields
        
        if dependencies["documents"] or dependencies["embeddables"]:
            metadata["dependencies"] = dependencies
        
        return metadata
    
    def _extract_dependencies(self, properties: Dict) -> Dict[str, List[str]]:
        """Extrae dependencias de documentos y embeddables"""
        documents = set()
        embeddables = set()
        
        for field_name, field_props in properties.items():
            field_type = field_props.get('type')
            
            if field_type == 'reference':
                target = field_props.get('reference_metadata', {}).get('target_entity')
                if target:
                    documents.add(target)
            
            elif field_type == 'collection':
                target = field_props.get('collection_metadata', {}).get('element_entity')
                if target:
                    documents.add(target)
            
            elif field_type in ['object_array', 'set']:
                metadata = field_props.get('array_metadata', {})
                element_type = metadata.get('element_type')
                if element_type and element_type not in ['string', 'integer', 'number', 'boolean']:
                    # Asumir documento si no es primitivo
                    documents.add(element_type)
            
            elif field_type == 'embedded':
                # Por determinar si es documento o embeddable
                # Por ahora dejarlo en embeddables
                pass
        
        return {
            "documents": sorted(list(documents)),
            "embeddables": sorted(list(embeddables))
        }
    
    # ==================== NUEVAS UTILIDADES ====================
    
    def _get_current_entity_name(self) -> str:
        """Obtiene el nombre de la entidad actual siendo procesada"""
        return self._current_entity or "Unknown"
    
    def _resolve_path_pattern(self, pattern: str, target_entity: str) -> str:
        """Resuelve un patrón de path con dot notation"""
        # Convertir {field} a {EntityName.field}
        resolved = pattern
        
        # Si ya tiene dot notation, no modificar
        if '.' in pattern:
            return pattern
            
        # Convertir placeholders simples a dot notation
        placeholders = re.findall(r'\{([^}]+)\}', pattern)
        for placeholder in placeholders:
            if placeholder == 'id':
                # {id} se refiere al target entity
                resolved = resolved.replace('{id}', f'{{{target_entity}.id}}')
            elif placeholder == 'name':
                # {name} se refiere al target entity
                resolved = resolved.replace('{name}', f'{{{target_entity}.name}}')
            # Otros placeholders se asume que son del target entity
            elif '.' not in placeholder:
                resolved = resolved.replace(f'{{{placeholder}}}', f'{{{target_entity}.{placeholder}}}')
        
        return resolved
    
    def _pluralize(self, word: str) -> str:
        """Pluralización simple en inglés"""
        if word.endswith('y'):
            return word[:-1] + 'ies'
        elif word.endswith(('s', 'sh', 'ch', 'x', 'z')):
            return word + 'es'
        else:
            return word + 's'
    
    # ==================== UTILIDADES DE TIPOS CORREGIDAS ====================
    
    def _extract_base_type(self, annotation):
        """Extrae el tipo base de una anotación (sin Optional, List, etc.)"""
        # Manejar Union (Optional)
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None):
                    return self._extract_base_type(arg)
        
        # NO manejar contenedores aquí - eso se hace en _process_regular_field
        # Solo devolver el tipo directo
        return annotation
    
    def _extract_list_element_type(self, annotation):
        """Extrae tipo de elemento de List/Set con mejor detección"""
        # Manejar Optional[List[T]] o Optional[Set[T]]
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None):
                    return self._extract_list_element_type(arg)
        
        # Manejar List[T], Set[T], etc.
        if get_origin(annotation) in (list, set, tuple):
            args = get_args(annotation)
            if args:
                element_type = args[0]
                # Verificar que sea un tipo válido
                if inspect.isclass(element_type):
                    return element_type
                # Si no es clase, puede ser tipo primitivo
                return element_type
        
        return None
    
    def _is_list_type(self, annotation) -> bool:
        """Verifica si es tipo List (incluyendo Optional[List])"""
        # Manejar Optional[List[T]]
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None) and get_origin(arg) is list:
                    return True
        
        # List directo
        return get_origin(annotation) is list
    
    def _is_set_type(self, annotation) -> bool:
        """Verifica si es tipo Set (incluyendo Optional[Set])"""
        # Manejar Optional[Set[T]]
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None) and get_origin(arg) is set:
                    return True
        
        # Set directo
        return get_origin(annotation) is set
    
    def _is_tuple_type(self, annotation) -> bool:
        """Verifica si es tipo Tuple (incluyendo Optional[Tuple])"""
        # Manejar Optional[Tuple[T]]
        if get_origin(annotation) is Union:
            args = get_args(annotation)
            for arg in args:
                if arg is not type(None) and get_origin(arg) is tuple:
                    return True
        
        # Tuple directo
        return get_origin(annotation) is tuple


# Función helper para usar fácilmente
def generate_flat_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """Función helper para generar esquema flat"""
    generator = DocumentSchemaGenerator()
    return generator.generate_schema(model_class)