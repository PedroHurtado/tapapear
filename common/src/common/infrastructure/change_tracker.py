from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, ConfigDict
from .document import (
    Document,
    DocumentId,
    DocumentReference,
    CollectionReference,
    GeoPointValue,
)


class ChangeType(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class OperationType(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class ArrayOperation(Enum):
    SET = "set"
    UNION = "union"
    REMOVE = "remove"
    UNION_REMOVE = "union_remove"


class FieldOperation(Enum):
    SET = "set"
    DELETE = "delete"


# ==================== DATA CLASSES (Pydantic Frozen) ====================


class TrackedEntity(BaseModel):
    entity_id: Any  # Cambiar de Any a conservar el objeto original
    state: ChangeType
    current_document: Document
    original_snapshot: Dict
    entity_type: str

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class AbstractCommand(BaseModel):
    """Comando abstracto independiente de base de datos"""

    operation: OperationType
    entity_id: Union[DocumentId, CollectionReference]  # NUNCA Optional
    data: Dict[str, Any]
    deleted_fields: Optional[List[str]] = None
    array_operations: Optional[Dict[str, Dict]] = None
    level: int = 0

    model_config = ConfigDict(frozen=True)

    def __repr__(self):
        return f"AbstractCommand(operation={self.operation.value}, id={self.entity_id}, level={self.level})"


# ==================== DATABASE DIALECTS ====================


class DatabaseDialect(ABC):
    """Interfaz abstracta para dialectos de base de datos"""

    def __init__(self, db, transaction=None):
        self.db = db
        self.transaction = transaction

    @abstractmethod
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Ejecuta los comandos abstractos en la base de datos especÃ­fica"""
        pass

    @abstractmethod
    def sort_commands(
        self, commands: List[AbstractCommand], change_type: ChangeType
    ) -> List[AbstractCommand]:
        """Ordena los comandos segÃºn las reglas especÃ­ficas de la base de datos"""
        pass


# ==================== CHANGE TRACKER MEJORADO ====================


class ChangeTracker:
    def __init__(self, dialect: DatabaseDialect):
        self._tracked_entities: Dict[Any, TrackedEntity] = {}
        self.dialect = dialect
        self._collection_metadata: Dict[str, Dict[str, Dict]] = {}
        self._aggregate_schema: Dict = {}  # Guardar el schema del aggregate root

    def _get_metadata_collection(
        self, document: Document
    ) -> Dict[str, Dict[str, Dict]]:
        """Extrae metadata de collections desde el schema del aggregate root"""
        metadata_result = {}
        
        # Intentar obtener el schema del aggregate root
        schema = None
        if hasattr(document.__class__, '__document_schema__'):
            schema = document.__class__.__document_schema__
            self._aggregate_schema = schema  # Guardar para uso futuro
        
        if not schema:
            return metadata_result
        
        # Extraer collections de cada entidad en el schema
        for entity_name, entity_schema in schema.items():
            collection_fields = {}
            properties = entity_schema.get('properties', {})
            
            for field_name, field_schema in properties.items():
                field_type = field_schema.get('type')
                # Identificar collections por su tipo en el schema
                if field_type == 'collection':
                    collection_fields[field_name] = {'collection': True}
            
            metadata_result[entity_name] = collection_fields
        
        return metadata_result

    def set_entity(self, document: Document, state: ChangeType) -> None:
        """Establece o actualiza el estado de una entidad con validaciones internas"""

        if not self.is_tracked(document):
            # Primera vez que se trackea - crear snapshot
            original_snapshot = self._create_snapshot(document)

            # âœ… NUEVA LÃNEA: Extraer metadata recursivamente
            collection_metadata = self._get_metadata_collection(document)
            self._collection_metadata.update(collection_metadata)

            entity_data = TrackedEntity(
                entity_id=document.id,
                state=state,
                current_document=document,
                original_snapshot=original_snapshot,
                entity_type=document.__class__.__name__,
            )
            self._tracked_entities[document.id] = entity_data

        else:
            # Ya existe - validar transiciÃ³n y actualizar estado
            tracked = self._tracked_entities[document.id]

            if not self._is_valid_transition(tracked.state, state):
                raise ValueError(f"Invalid state transition: {tracked.state} â†’ {state}")

            # Crear nueva instancia frozen con estado actualizado
            updated_entity = tracked.model_copy(update={"state": state})
            self._tracked_entities[document.id] = updated_entity

    def get_tracked_entity(self, document: Document) -> Optional[Document]:
        """Devuelve la instancia del Document trackeado"""
        tracked = self._tracked_entities.get(document.id)
        return tracked.current_document if tracked else None

    def is_tracked(self, document: Document) -> bool:
        return document.id in self._tracked_entities

    def save_changes(self) -> None:
        for entity_id, tracked_entity in self._tracked_entities.items():
            entity_commands = []

            match tracked_entity.state:
                case ChangeType.ADDED:
                    entity_commands = self._generate_create_commands(tracked_entity)

                case ChangeType.MODIFIED:
                    entity_commands = self._generate_update_commands(tracked_entity)

                case ChangeType.DELETED:
                    entity_commands = self._generate_delete_commands(tracked_entity)

                case ChangeType.UNCHANGED:
                    # No hacer nada
                    continue

            # Delegar el ordenamiento al dialect especÃ­fico
            if entity_commands:
                sorted_commands = self.dialect.sort_commands(
                    entity_commands, tracked_entity.state
                )
                self.dialect.execute_commands(sorted_commands)

    def _generate_create_commands(
        self, tracked_entity: TrackedEntity
    ) -> List[AbstractCommand]:
        """Genera comandos CREATE recursivos para toda la estructura"""
        commands = []
        
        current_snapshot = self._create_snapshot(tracked_entity.current_document)
        filtered_snapshot = self._filter_none_recursive(current_snapshot)
        
        self._generate_recursive_commands(
            data=filtered_snapshot,
            level=0,
            commands=commands,
            operation=OperationType.CREATE,
            entity_type=tracked_entity.entity_type,
        )

        return commands

    def _generate_delete_commands(
        self, tracked_entity: TrackedEntity
    ) -> List[AbstractCommand]:
        """Genera comandos DELETE recursivos para toda la estructura"""
        commands = []
        snapshot = tracked_entity.original_snapshot

        # Mismo algoritmo que CREATE, solo cambia el OperationType
        # El dialect se encarga de ordenar correctamente
        self._generate_recursive_commands(
            data=snapshot, level=0, commands=commands, operation=OperationType.DELETE
        )

        return commands

    def _generate_update_commands(
        self, tracked_entity: TrackedEntity
    ) -> List[AbstractCommand]:
        """Genera comandos UPDATE/CREATE/DELETE para una entidad modificada"""
        commands = []

        # Analizar diferencias
        changes = self._diff(
            tracked_entity.original_snapshot,
            self._create_snapshot(tracked_entity.current_document),
        )

        # Procesar cambios en campos simples y campos eliminados
        update_data = {}
        deleted_fields = []

        if changes["fields_changed"]:
            for field_path, change in changes["fields_changed"].items():
                if not self._is_nested_list_field(field_path):
                    update_data[field_path] = change["new_value"]

        if changes["fields_deleted"]:
            deleted_fields = [
                field
                for field in changes["fields_deleted"]
                if not self._is_nested_list_field(field)
            ]

        # Procesar operaciones de array
        array_operations = None
        if changes["lists_changed"]:
            array_operations = self._detect_array_operations(changes["lists_changed"])

        # Crear comando UPDATE si hay cambios
        if update_data or deleted_fields or array_operations:
            # Usar el ID serializado del snapshot, no el atributo Python
            snapshot = self._create_snapshot(tracked_entity.current_document)

            command = AbstractCommand(
                operation=OperationType.UPDATE,
                entity_id=snapshot[
                    "id"
                ],  # Usar el objeto serializado (DocumentId/CollectionReference)
                data=update_data,
                deleted_fields=deleted_fields if deleted_fields else None,
                array_operations=array_operations,
                level=0,
            )
            commands.append(command)

        # Procesar cambios en listas (CREATE/DELETE de elementos anidados)
        if changes["lists_changed"]:
            commands.extend(
                self._generate_nested_list_commands(
                    changes["lists_changed"],
                    tracked_entity.current_document.id,  # âœ… Pasar DocumentId directamente
                )
            )

        return commands

    def _generate_nested_list_commands(
        self, lists_changes: Dict, parent_id: Any
    ) -> List[AbstractCommand]:
        """Genera comandos para cambios en documentos anidados en listas"""
        commands = []

        for list_path, changes in lists_changes.items():
            # Items aÃ±adidos - generar CREATE recursivo
            for added_item in changes.get("added", []):
                entity_id, _ = self._extract_entity_id_and_data(added_item)
                if entity_id:
                    self._generate_recursive_commands(
                        data=added_item,
                        level=1,
                        commands=commands,
                        operation=OperationType.CREATE,
                    )

            # Items eliminados - generar DELETE recursivo
            for removed_item in changes.get("removed", []):
                entity_id, _ = self._extract_entity_id_and_data(removed_item)
                if entity_id:
                    self._generate_recursive_commands(
                        data=removed_item,
                        level=1,
                        commands=commands,
                        operation=OperationType.DELETE,
                    )

            # Items modificados - generar UPDATE recursivo
            for modified_item in changes.get("modified", []):
                item_id = modified_item["id"]
                item_changes = modified_item["changes"]

                # Generar UPDATE para el item modificado
                update_data = {}
                deleted_fields = []
                array_operations = None

                if item_changes.get("fields_changed"):
                    for field_path, change in item_changes["fields_changed"].items():
                        update_data[field_path] = change["new_value"]

                if item_changes.get("fields_deleted"):
                    deleted_fields = item_changes["fields_deleted"]

                if item_changes.get("lists_changed"):
                    array_operations = self._detect_array_operations(
                        item_changes["lists_changed"]
                    )

                if update_data or deleted_fields or array_operations:
                    # Convertir string a DocumentId si es necesario
                    item_id_raw = modified_item["id"]
                    if isinstance(item_id_raw, str):
                        item_id_obj = DocumentId(path=item_id_raw)
                    else:
                        item_id_obj = item_id_raw

                    command = AbstractCommand(
                        operation=OperationType.UPDATE,
                        entity_id=item_id_obj,
                        data=update_data,
                        deleted_fields=deleted_fields if deleted_fields else None,
                        array_operations=array_operations,
                        level=1,
                    )
                    commands.append(command)

        return commands

    def _generate_recursive_commands(
        self,
        data: Dict,
        level: int,
        commands: List[AbstractCommand],
        operation: OperationType,
        entity_type: str = None,
    ):       
        
    
    # 1. Extraer entity_id       

        # 1. Extraer entity_id por tipo y obtener data sin ese campo
        entity_id, clean_data = self._extract_entity_id_and_data(data)

        if not entity_id:
            return        

        # 3. Recorrer UNA sola vez: separar collections de command data
        final_command_data = {}
        collections_to_process = []

        for field_name, field_value in clean_data.items():
            # Excluir campos especiales
            if field_name.startswith("__"):
                continue

            if self._is_collection_field(field_name, field_value, entity_type):
                # Es collection â†’ guardar para procesar recursivamente
                collections_to_process.append((field_name, field_value))
            else:
                # No es collection â†’ incluir en command data
                final_command_data[field_name] = field_value

        # 4. Crear comando (vacÃ­o para DELETE)
        command_data = final_command_data if operation != OperationType.DELETE else {}
        command = AbstractCommand(
            operation=operation, entity_id=entity_id, data=command_data, level=level
        )
        commands.append(command)

        # 5. Procesar collections recursivamente
        for field_name, field_value in collections_to_process:
            if isinstance(field_value, list):
                for nested_doc in field_value:
                    if isinstance(nested_doc, dict):
                        nested_entity_id, _ = self._extract_entity_id_and_data(
                            nested_doc
                        )
                        if nested_entity_id:
                            # Inferir entity_type del nested_doc
                            nested_entity_type = nested_doc.get("__class__", None)
                            self._generate_recursive_commands(
                                data=nested_doc,
                                level=level + 1,
                                commands=commands,
                                operation=operation,
                                entity_type=nested_entity_type,
                            )

    # ==================== NUEVOS HELPERS ====================

    def _extract_entity_id_and_data(
        self, data: Dict
    ) -> tuple[Optional[Union[DocumentId, CollectionReference]], Dict]:
        """
        Extrae el entity_id buscando por tipo DocumentId/CollectionReference
        Retorna tupla (entity_id, data_sin_ese_campo)
        """
        entity_id = None
        entity_id_field = None

        # Buscar el campo que contenga DocumentId o CollectionReference
        for field_name, field_value in data.items():
            if isinstance(field_value, (DocumentId, CollectionReference)):
                entity_id = field_value
                entity_id_field = field_name
                break

        # Crear copia del data sin el campo entity_id
        if entity_id_field:
            clean_data = {k: v for k, v in data.items() if k != entity_id_field}
        else:
            clean_data = data.copy()

        return entity_id, clean_data

    def _filter_none_recursive(self, data: Any) -> Any:
        """Filtra None values recursivamente para CREATE"""
        if isinstance(data, dict):
            return {
                k: self._filter_none_recursive(v)
                for k, v in data.items()
                if v is not None
            }
        elif isinstance(data, list):
            return [
                self._filter_none_recursive(item) for item in data if item is not None
            ]
        else:
            # Para objetos como DocumentId, CollectionReference, GeoPointValue, etc.
            # NO procesar recursivamente, devolver tal como estÃ¡n
            return data

    def _compare_special_types(self, orig: Any, curr: Any) -> bool:
        """Compara valores manejando tipos especiales de Document.py"""

        # Si ambos son None
        if orig is None and curr is None:
            return True

        # Si uno es None y el otro no
        if (orig is None) != (curr is None):
            return False

        # Si son tipos especiales de Document.py
        if isinstance(
            orig, (DocumentId, DocumentReference, CollectionReference)
        ) and isinstance(curr, (DocumentId, DocumentReference, CollectionReference)):
            return orig.path == curr.path

        if isinstance(orig, GeoPointValue) and isinstance(curr, GeoPointValue):
            return orig.latitude == curr.latitude and orig.longitude == curr.longitude

        # ComparaciÃ³n normal
        return orig == curr

    def _detect_array_operations(
        self, lists_changed: Dict
    ) -> Optional[Dict[str, Dict]]:
        """Convierte cambios de lista a ArrayOperations"""
        array_operations = {}

        for list_path, changes in lists_changed.items():
            added = changes.get("added", [])
            removed = changes.get("removed", [])

            # Solo procesar arrays de elementos simples (no documentos anidados)
            # Los documentos anidados se manejan con comandos CREATE/DELETE separados
            if added or removed:
                # Filtrar solo elementos que NO son documentos (no tienen entity_id)
                simple_added = []
                simple_removed = []

                for item in added:
                    if isinstance(item, dict):
                        entity_id, _ = self._extract_entity_id_and_data(item)
                        if not entity_id:
                            simple_added.append(item)
                    else:
                        simple_added.append(item)

                for item in removed:
                    if isinstance(item, dict):
                        entity_id, _ = self._extract_entity_id_and_data(item)
                        if not entity_id:
                            simple_removed.append(item)
                    else:
                        simple_removed.append(item)

                if simple_added or simple_removed:
                    array_operations[list_path] = self._build_array_operation(
                        simple_added, simple_removed
                    )

        return array_operations if array_operations else None

    def _build_array_operation(self, added: List, removed: List) -> Dict:
        """Construye operaciÃ³n UNION/REMOVE/UNION_REMOVE segÃºn cambios"""

        if added and removed:
            return {
                "operation": ArrayOperation.UNION_REMOVE,
                "union": added,
                "remove": removed,
            }
        elif added:
            return {"operation": ArrayOperation.UNION, "items": added}
        elif removed:
            return {"operation": ArrayOperation.REMOVE, "items": removed}
        else:
            # Caso raro - SET completo
            return {
                "operation": ArrayOperation.SET,
                "items": added,  # En este caso serÃ­a el array completo
            }

    # ==================== MÃ‰TODOS MODIFICADOS ====================

    def _is_collection_field(
        self, field_name: str, field_value: Any, entity_type: str = None
    ) -> bool:
        """Determina si un campo es una collection usando metadata cache"""
        if entity_type and entity_type in self._collection_metadata:
            return field_name in self._collection_metadata[entity_type]

        # Fallback al mÃ©todo anterior si no hay metadata
        if not isinstance(field_value, list):
            return False

        # Si la lista estÃ¡ vacÃ­a, asumir que no es collection
        if not field_value:
            return False

        # Verificar si el primer elemento es un documento (tiene entity_id)
        first_item = field_value[0]

        if isinstance(first_item, dict):
            entity_id, _ = self._extract_entity_id_and_data(first_item)
            return entity_id is not None

        return False

    def _filter_command_data(self, data: Dict, entity_type: str = None) -> Dict:
        """Filtra los datos para el comando, excluyendo collections usando metadata"""
        filtered_data = {}

        for key, value in data.items():
            # Excluir campos especiales
            if key.startswith("__"):
                continue

            # Excluir collections usando metadata cache
            if self._is_collection_field(key, value, entity_type):
                continue

            # INCLUIR TODO - DocumentReference, GeoPointValue, etc.
            # El dialecto decidirÃ¡ quÃ© hacer con cada tipo
            filtered_data[key] = value

        return filtered_data

    def _diff(self, original, current, path="root"):
        """
        Compara dos estructuras y devuelve cambios incluyendo detecciÃ³n de campos eliminados:
            {
                "fields_changed": {...},
                "fields_deleted": [...],  # NUEVO
                "lists_changed": {...}
            }
        """

        def _compare(orig, curr, path):
            # Casos donde uno es None
            if orig is None and curr is None:
                return {"fields_changed": {}, "fields_deleted": [], "lists_changed": {}}

            if orig is None and curr is not None:
                return {
                    "fields_changed": {path: {"old_value": None, "new_value": curr}},
                    "fields_deleted": [],
                    "lists_changed": {},
                }

            if orig is not None and curr is None:
                return {
                    "fields_changed": {},
                    "fields_deleted": [path],
                    "lists_changed": {},
                }

            # Tipos distintos
            if type(orig) != type(curr):
                return {
                    "fields_changed": {path: {"old_value": orig, "new_value": curr}},
                    "fields_deleted": [],
                    "lists_changed": {},
                }

            # Escalar (valores primitivos y tipos especiales)
            if not isinstance(orig, (dict, list)):
                if not self._compare_special_types(orig, curr):
                    return {
                        "fields_changed": {
                            path: {"old_value": orig, "new_value": curr}
                        },
                        "fields_deleted": [],
                        "lists_changed": {},
                    }
                return {"fields_changed": {}, "fields_deleted": [], "lists_changed": {}}

            # Dict
            if isinstance(orig, dict):
                fields_changed = {}
                fields_deleted = []
                lists_changed = {}

                # Obtener todas las claves (menos __class__)
                all_keys = (set(orig.keys()) | set(curr.keys())) - {"__class__"}

                for key in all_keys:
                    new_path = f"{path}.{key}" if path != "root" else key

                    if key not in orig:
                        # Campo aÃ±adido
                        if curr[key] is not None:
                            fields_changed[new_path] = {
                                "old_value": None,
                                "new_value": curr[key],
                            }
                    elif key not in curr:
                        # Campo eliminado completamente
                        fields_deleted.append(new_path)
                    else:
                        # Campo existe en ambos
                        if orig[key] is not None and curr[key] is None:
                            # Valor â†’ None = DELETE
                            fields_deleted.append(new_path)
                        elif not self._compare_special_types(orig[key], curr[key]):
                            # Comparar recursivamente para estructuras complejas
                            sub_result = _compare(orig[key], curr[key], new_path)
                            fields_changed.update(sub_result["fields_changed"])
                            fields_deleted.extend(sub_result["fields_deleted"])
                            lists_changed.update(sub_result["lists_changed"])

                return {
                    "fields_changed": fields_changed,
                    "fields_deleted": fields_deleted,
                    "lists_changed": lists_changed,
                }

            # List
            if isinstance(orig, list):
                # Verificar si es una lista vacÃ­a
                if not orig and not curr:
                    return {
                        "fields_changed": {},
                        "fields_deleted": [],
                        "lists_changed": {},
                    }

                # Verificar si es una lista de dicts con entity_id
                is_list_with_ids = False
                if orig and isinstance(orig[0], dict):
                    entity_id, _ = self._extract_entity_id_and_data(orig[0])
                    is_list_with_ids = entity_id is not None
                elif curr and isinstance(curr[0], dict):
                    entity_id, _ = self._extract_entity_id_and_data(curr[0])
                    is_list_with_ids = entity_id is not None

                if is_list_with_ids:
                    # Lista de objetos con ID
                    orig_by_id = {}
                    curr_by_id = {}

                    for x in orig:
                        if isinstance(x, dict):
                            entity_id, _ = self._extract_entity_id_and_data(x)
                            if entity_id:
                                orig_by_id[entity_id.path] = x

                    for x in curr:
                        if isinstance(x, dict):
                            entity_id, _ = self._extract_entity_id_and_data(x)
                            if entity_id:
                                curr_by_id[entity_id.path] = x

                    added = []
                    removed = []
                    modified = []

                    # Elementos aÃ±adidos
                    for item_id in curr_by_id.keys() - orig_by_id.keys():
                        added.append(curr_by_id[item_id])

                    # Elementos eliminados
                    for item_id in orig_by_id.keys() - curr_by_id.keys():
                        removed.append(orig_by_id[item_id])

                    # Elementos modificados
                    fields_changed = {}
                    fields_deleted = []
                    lists_changed = {}

                    for item_id in orig_by_id.keys() & curr_by_id.keys():
                        item_path = f"{path}[id={item_id}]"
                        sub_result = _compare(
                            orig_by_id[item_id], curr_by_id[item_id], item_path
                        )

                        # Si hay cambios en este item, agregarlo a modified
                        if (
                            sub_result["fields_changed"]
                            or sub_result["fields_deleted"]
                            or sub_result["lists_changed"]
                        ):
                            modified.append({"id": item_id, "changes": sub_result})

                        # TambiÃ©n propagar los cambios de campos individuales
                        fields_changed.update(sub_result["fields_changed"])
                        fields_deleted.extend(sub_result["fields_deleted"])
                        lists_changed.update(sub_result["lists_changed"])

                    # Agregar informaciÃ³n de la lista si hay cambios estructurales
                    result = {
                        "fields_changed": fields_changed,
                        "fields_deleted": fields_deleted,
                        "lists_changed": lists_changed,
                    }

                    if added or removed or modified:
                        result["lists_changed"][path] = {
                            "added": added,
                            "removed": removed,
                            "modified": modified,
                        }

                    return result
                else:
                    # Lista simple (sin IDs) - comparaciÃ³n directa
                    if not self._compare_special_types(orig, curr):
                        return {
                            "fields_changed": {
                                path: {"old_value": orig, "new_value": curr}
                            },
                            "fields_deleted": [],
                            "lists_changed": {},
                        }
                    return {
                        "fields_changed": {},
                        "fields_deleted": [],
                        "lists_changed": {},
                    }

        # Ejecutar la comparaciÃ³n
        result = _compare(original, current, "root")
        return result

    def _is_nested_list_field(self, field_path: str) -> bool:
        """Verifica si un campo pertenece a una lista anidada"""
        return "[id=" in field_path

    def _is_valid_transition(
        self, current_state: ChangeType, new_state: ChangeType
    ) -> bool:
        """Valida si una transiciÃ³n de estado es permitida"""
        valid_transitions = {
            ChangeType.UNCHANGED: [ChangeType.MODIFIED, ChangeType.DELETED],
            ChangeType.MODIFIED: [],  # No puede cambiar a ningÃºn estado
            ChangeType.ADDED: [],  # No puede cambiar a ningÃºn estado
            ChangeType.DELETED: [],  # No puede cambiar a ningÃºn estado
        }
        return new_state in valid_transitions.get(current_state, [])

    def _create_snapshot(self, document: Document) -> Dict:
        if hasattr(document, 'model_dump_aggregate_root'):
            snapshot = document.model_dump_aggregate_root(mode="python")
        else:
            snapshot = document.model_dump()
        return snapshot

    def clear(self) -> None:
        """Limpia el tracking (al cerrar transacciÃ³n)"""
        self._tracked_entities.clear()
        self._collection_metadata.clear()