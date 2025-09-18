"""
ODM Change Tracking Module
Proporciona funcionalidad de tracking de cambios estilo ORM para diferentes bases de datos.
"""

from abc import ABC, abstractmethod
from contextvars import ContextVar
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from uuid import UUID
from deepdiff import DeepDiff

# ==================== ENUMS ====================

class ChangeType(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


# ==================== DATA CLASSES ====================

class TrackedEntity:
    """Representa una entidad siendo trackeada por el ChangeTracker"""
    
    def __init__(self, entity_id: UUID, state: ChangeType, data: Dict[str, Any], entity_type: str):
        self.entity_id = entity_id
        self.state = state
        self.data = data
        self.entity_type = entity_type


class AbstractCommand:
    """Comando abstracto independiente de base de datos"""
    
    def __init__(self, operation: str, entity_path: str, data: Dict[str, Any], level: int = 0):
        self.operation = operation  # "CREATE", "UPDATE", "DELETE"
        self.entity_path = entity_path
        self.data = data
        self.level = level
    
    def __repr__(self):
        return f"AbstractCommand(operation={self.operation}, path={self.entity_path}, level={self.level})"


# ==================== DATABASE DIALECTS ====================

class DatabaseDialect(ABC):
    """Interfaz abstracta para dialectos de base de datos"""
    
    def __init__(self, db, transaction=None):
        self.db = db
        self.transaction = transaction
    
    @abstractmethod
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Ejecuta los comandos abstractos en la base de datos específica"""
        pass


class FirestoreDialect(DatabaseDialect):
    """Dialecto para Google Firestore"""
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Ejecuta comandos en Firestore"""
        for command in commands:
            doc_ref = self._create_doc_ref_from_path(command.entity_path)
            firestore_data = self._convert_to_firestore_data(command.data)
            
            if command.operation == "CREATE":
                if self.transaction:
                    self.transaction.create(doc_ref, firestore_data)
                else:
                    # Para async, necesitarías await aquí
                    doc_ref.create(firestore_data)
            
            elif command.operation == "UPDATE":
                if self.transaction:
                    self.transaction.update(doc_ref, firestore_data)
                else:
                    doc_ref.update(firestore_data)
            
            elif command.operation == "DELETE":
                if self.transaction:
                    self.transaction.delete(doc_ref)
                else:
                    doc_ref.delete()
    
    def _create_doc_ref_from_path(self, path: str):
        """Crea AsyncDocumentReference desde path usando db.collection().document()"""
        path_parts = path.split('/')
        doc_ref = self.db
        
        for i in range(0, len(path_parts), 2):
            if i < len(path_parts):
                doc_ref = doc_ref.collection(path_parts[i])
            if i + 1 < len(path_parts):
                doc_ref = doc_ref.document(path_parts[i + 1])
        
        return doc_ref
    
    def _convert_to_firestore_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convierte datos abstractos a formato Firestore"""
        # Aquí aplicarías convert_document_references si fuera necesario
        return data


# ==================== CHANGE TRACKER ====================

class ChangeTracker:
    """Tracker de cambios estilo ORM con soporte para múltiples dialectos de BD"""
    
    def __init__(self, dialect: DatabaseDialect):
        self._tracked_entities: Dict[UUID, TrackedEntity] = {}
        self._dialect = dialect
    
    def track_entity(self, document, state: ChangeType) -> None:
        """Registra un documento en el tracking"""
        entity_data = TrackedEntity(
            entity_id=document.id,
            state=state,
            data=document.model_dump(context={"is_root": True}),
            entity_type=document.__class__.__name__
        )
        self._tracked_entities[document.id] = entity_data
    
    def _get_main_document_path(self, data: Dict[str, Any]) -> str:
        """Obtiene el path del documento principal desde los datos"""
        # El documento principal tiene el ID en el nivel raíz
        if 'id' in data:
            root_id = data['id']
            if isinstance(root_id, str):  # ID simple del documento raíz
                # Buscar el tipo de entidad en las entidades trackeadas
                for tracked_entity in self._tracked_entities.values():
                    if str(tracked_entity.entity_id) == root_id:
                        # Para la entidad root, pluralizar manualmente ya que no pasa por MixinSerializer
                        collection_name = self._pluralize_class_name(tracked_entity.entity_type)
                        return f"{collection_name}/{root_id}"
                
                # Fallback si no encontramos la entidad trackeada
                return f"documents/{root_id}"
        return ""
    
    def _pluralize_class_name(self, class_name: str) -> str:
        """Convierte nombre de clase a plural para collection name"""
        word = class_name.lower()
        if word.endswith('y'):
            return word[:-1] + 'ies'
        elif word.endswith(('s', 'sh', 'ch', 'x', 'z')):
            return word + 'es'
        else:
            return word + 's'
    
    def get_tracked_entity(self, document_id: UUID) -> Optional[TrackedEntity]:
        """Obtiene una entidad del tracking"""
        return self._tracked_entities.get(document_id)
    
    def is_tracked(self, document) -> bool:
        """Verifica si un documento está siendo trackeado"""
        return document.id in self._tracked_entities
    
    def save_changes(self) -> None:
        """Ejecuta todos los cambios pendientes (como commit)"""
        all_commands = []
        
        # Separar comandos por tipo para ordenarlos correctamente
        create_commands = []
        update_commands = []
        delete_commands = []
        
        for tracked_entity in self._tracked_entities.values():
            if tracked_entity.state == ChangeType.ADDED:
                commands = self._generate_create_commands_from_data(tracked_entity.data)
                create_commands.extend(commands)
            
            elif tracked_entity.state == ChangeType.MODIFIED:
                # Para MODIFIED, necesitamos comparar con el estado original
                # Por ahora, regeneramos todos los comandos CREATE 
                # En una implementación completa, harías diff aquí
                commands = self._generate_create_commands_from_data(tracked_entity.data)
                update_commands.extend(commands)
            
            elif tracked_entity.state == ChangeType.DELETED:
                commands = self._generate_delete_commands_from_data(tracked_entity.data)
                delete_commands.extend(commands)
        
        # Ordenar comandos:
        # 1. CREATE: por nivel ascendente (padres primero)
        # 2. UPDATE: por nivel ascendente  
        # 3. DELETE: por nivel descendente (hijos primero)
        create_commands.sort(key=lambda cmd: cmd.level)
        update_commands.sort(key=lambda cmd: cmd.level)
        delete_commands.sort(key=lambda cmd: cmd.level, reverse=True)
        
        # Combinar todos los comandos en orden de ejecución
        all_commands = create_commands + update_commands + delete_commands
        
        if all_commands:
            print(f"🚀 ChangeTracker: Executing {len(all_commands)} commands...")
            print(f"   📊 CREATE: {len(create_commands)}, UPDATE: {len(update_commands)}, DELETE: {len(delete_commands)}")
        
        # Ejecutar todos los comandos
        self._dialect.execute_commands(all_commands)
        
        # Limpiar tracking después del commit
        self.clear()
    
    def clear(self) -> None:
        """Limpia el tracking"""
        self._tracked_entities.clear()
    
    def _generate_create_commands(self, document) -> List[AbstractCommand]:
        """Genera comandos CREATE para un documento y sus subcollections"""
        data = document.model_dump(context={"is_root": True})
        return self._generate_create_commands_from_data(data)
    
    def _generate_create_commands_from_data(self, data: Dict[str, Any]) -> List[AbstractCommand]:
        """Genera comandos CREATE desde datos serializados"""
        commands = []
        processed_paths = set()  # Para evitar duplicaciones
        
        # PRIMERO: Agregar comando para el documento principal
        main_doc_path = self._get_main_document_path(data)
        if main_doc_path:
            main_doc_data = self._get_main_document_data(data)
            commands.append(AbstractCommand("CREATE", main_doc_path, main_doc_data, 1))
            processed_paths.add(main_doc_path)
        
        def extract_commands(obj: Any, current_path: str = "", level: int = 0):
            if isinstance(obj, dict):
                # Si tiene CollectionReference como id, es un documento para crear
                if 'id' in obj and self._is_collection_reference(obj['id']):
                    entity_path = self._get_path_from_id(obj['id'])
                    
                    # Evitar duplicaciones
                    if entity_path in processed_paths:
                        return
                    processed_paths.add(entity_path)
                    
                    # Separar datos de subcollections - solo incluir campos que no contengan CollectionReference
                    doc_data = {}
                    for key, value in obj.items():
                        if key == 'id':
                            continue
                        
                        # Si el valor contiene CollectionReference, no incluirlo en doc_data
                        if not self._contains_collection_reference(value):
                            doc_data[key] = value
                    
                    command_level = len(entity_path.split('/')) // 2
                    commands.append(AbstractCommand("CREATE", entity_path, doc_data, command_level))
                    
                    # Procesar subcollections anidadas
                    for key, value in obj.items():
                        if key != 'id' and self._contains_collection_reference(value):
                            extract_commands(value, entity_path, level + 1)
                
                else:
                    # Dict normal, procesar recursivamente
                    for key, value in obj.items():
                        extract_commands(value, f"{current_path}/{key}" if current_path else key, level)
            
            elif isinstance(obj, (list, set)):
                for item in obj:
                    extract_commands(item, current_path, level)
        
        # SEGUNDO: Extraer comandos de subcollections
        extract_commands(data)
        
        return commands
    
    def _get_main_document_path(self, data: Dict[str, Any]) -> str:
        """Obtiene el path del documento principal desde los datos"""
        # El documento principal tiene el ID en el nivel raíz
        if 'id' in data:
            root_id = data['id']
            if isinstance(root_id, str):  # ID simple del documento raíz
                # Necesitamos construir el path basado en el tipo de documento
                # Por ahora, asumimos que es "users" - esto debería mejorarse
                return f"users/{root_id}"
        return ""
    
    def _get_main_document_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Obtiene los datos del documento principal (sin subcollections)"""
        main_data = {}
        for key, value in data.items():
            if key == 'id':
                continue
            
            # Solo incluir campos que no contengan CollectionReference
            if not self._contains_collection_reference(value):
                main_data[key] = value
        
        return main_data
    
    def _is_collection_reference(self, obj: Any) -> bool:
        """Verifica si un objeto es CollectionReference"""
        # Puede ser una instancia de CollectionReference o un dict serializado con 'path'
        if hasattr(obj, 'path') and hasattr(obj, '__class__'):
            return 'CollectionReference' in obj.__class__.__name__
        
        # O puede ser un dict serializado desde CollectionReference
        if isinstance(obj, dict) and 'path' in obj and len(obj) == 1:
            return True
            
        return False
    
    def _get_path_from_id(self, id_obj: Any) -> str:
        """Extrae el path de un objeto id (CollectionReference o dict)"""
        if hasattr(id_obj, 'path'):
            return id_obj.path
        elif isinstance(id_obj, dict) and 'path' in id_obj:
            return id_obj['path']
        else:
            return str(id_obj)  # Fallback para IDs simples
    
    def _contains_collection_reference(self, obj: Any) -> bool:
        """Verifica si un objeto o estructura contiene CollectionReference"""
        if self._is_collection_reference(obj):
            return True
        
        if isinstance(obj, dict):
            return any(self._contains_collection_reference(v) for v in obj.values())
        
        if isinstance(obj, (list, set, tuple)):
            return any(self._contains_collection_reference(item) for item in obj)
        
        return False
    
    def _generate_update_commands(self, updated_document) -> List[AbstractCommand]:
        """Genera comandos UPDATE comparando estado tracked vs actual"""
        tracked = self.get_tracked_entity(updated_document.id)
        if not tracked:
            # Si no está trackeado, tratarlo como ADDED
            return self._generate_create_commands(updated_document)
        
        return self._calculate_diff_commands(tracked.data, updated_document)
    
    def _generate_delete_commands(self, document) -> List[AbstractCommand]:
        """Genera comandos DELETE en orden inverso (cascada)"""
        return self._generate_delete_commands_from_data(document.model_dump(context={"is_root": True}))
    
    def _generate_delete_commands_from_data(self, data: Dict[str, Any]) -> List[AbstractCommand]:
        """Genera comandos DELETE desde datos serializados"""
        create_commands = self._generate_create_commands_from_data(data)
        
        # Convertir CREATE a DELETE en orden inverso
        delete_commands = []
        for cmd in reversed(create_commands):
            delete_commands.append(AbstractCommand("DELETE", cmd.entity_path, {}, cmd.level))
        
        return delete_commands
    
    def _calculate_diff_commands(self, original_data: Dict[str, Any], updated_document) -> List[AbstractCommand]:
        """Calcula diferencias usando DeepDiff y genera comandos"""
        current_data = updated_document.model_dump(context={"is_root": True})
        
        diff = DeepDiff(original_data, current_data, ignore_order=True)
        return self._convert_diff_to_commands(diff)
    
    def _convert_diff_to_commands(self, diff: DeepDiff) -> List[AbstractCommand]:
        """Convierte resultado de DeepDiff a comandos abstractos"""
        commands = []
        
        # Items añadidos → CREATE
        for path in diff.get('dictionary_item_added', []):
            # Parsear path y extraer datos
            # Esto requiere lógica específica según la estructura de DeepDiff
            commands.append(AbstractCommand("CREATE", self._parse_diff_path(path), {}, 0))
        
        # Items eliminados → DELETE
        for path in diff.get('dictionary_item_removed', []):
            commands.append(AbstractCommand("DELETE", self._parse_diff_path(path), {}, 0))
        
        # Valores cambiados → UPDATE
        for path, change in diff.get('values_changed', {}).items():
            new_value = change['new_value']
            commands.append(AbstractCommand("UPDATE", self._parse_diff_path(path), {"value": new_value}, 0))
        
        return commands
    
    def _parse_diff_path(self, diff_path: str) -> str:
        """Convierte path de DeepDiff a entity_path"""
        # DeepDiff usa formato: "root['field']['subfield']"
        # Convertir a formato de entity path
        return diff_path.replace("root", "").replace("['", "/").replace("']", "").strip("/")


# ==================== CONTEXT HELPERS ====================

_change_tracker: ContextVar[Optional[ChangeTracker]] = ContextVar('change_tracker', default=None)


def get_change_tracker() -> Optional[ChangeTracker]:
    """Obtiene el ChangeTracker del contexto actual"""
    return _change_tracker.get()


def set_change_tracker(tracker: ChangeTracker) -> None:
    """Establece el ChangeTracker en el contexto actual"""
    _change_tracker.set(tracker)


def clear_change_tracker() -> None:
    """Limpia el ChangeTracker del contexto actual"""
    _change_tracker.set(None)


# ==================== PUBLIC API ====================




# Eliminar

from typing import List, Dict, Any
from datetime import datetime
import json
class ConsoleDialect(DatabaseDialect):
    """Dialecto que muestra los comandos en consola en lugar de ejecutarlos"""
    
    def __init__(self, db=None, transaction=None):
        super().__init__(db, transaction)
        self.db_name = "🔥 Firestore DB (Mock)" if db is None else str(db)
        self.transaction_name = "📦 Transaction (Mock)" if transaction else "🚫 No Transaction"
        self.command_count = 0
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Muestra los comandos en consola con formato bonito"""
        if not commands:
            print("✅ No commands to execute")
            return
        
        print(f"\n{'='*60}")
        print(f"🚀 EXECUTING {len(commands)} COMMANDS")
        print(f"🔗 Database: {self.db_name}")
        print(f"📦 Transaction: {self.transaction_name}")
        print(f"⏰ Started at: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")
        
        for i, command in enumerate(commands, 1):
            self.command_count += 1
            
            print(f"\n[{i:02d}/{len(commands)}] Command #{self.command_count}")
            print(f"{'─'*50}")
            print(self._format_command(command))
            print(f"🔥 Firestore: {self._to_firestore_command(command)}")
        
        print(f"\n{'='*60}")
        print(f"✅ EXECUTION COMPLETED")
        print(f"📊 Total commands executed: {len(commands)}")
        print(f"⏰ Finished at: {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}\n")
    
    def _format_command(self, command: AbstractCommand) -> str:
        """Formatea un comando para mostrar en consola"""
        indent = "  " * command.level
        data_preview = self._format_data(command.data) if command.data else "{}"
        
        return (f"{indent}📝 {command.operation} → {command.entity_path}\n"
               f"{indent}   Level: {command.level}\n"
               f"{indent}   Data: {data_preview}")
    
    def _format_data(self, data: Dict[str, Any]) -> str:
        """Formatea los datos para mostrar"""
        if not data:
            return "{}"
        
        # Limitar la salida para evitar spam en consola
        if len(str(data)) > 200:
            preview = {k: "..." if len(str(v)) > 50 else v for k, v in list(data.items())[:3]}
            if len(data) > 3:
                preview["..."] = f"and {len(data) - 3} more fields"
            return json.dumps(preview, default=str, separators=(',', ':'))
        
        return json.dumps(data, default=str, separators=(',', ':'))
    
    def _to_firestore_command(self, command: AbstractCommand) -> str:
        """Convierte a sintaxis de comando Firestore"""
        path_parts = command.entity_path.split('/')
        
        # Construir referencia estilo Firestore
        firestore_ref = "db"
        for i in range(0, len(path_parts), 2):
            if i < len(path_parts):
                firestore_ref += f".collection('{path_parts[i]}')"
            if i + 1 < len(path_parts):
                firestore_ref += f".document('{path_parts[i + 1]}')"
        
        # Generar comando según operación
        if command.operation == "CREATE":
            data_str = self._format_data(command.data)
            return f"{firestore_ref}.create({data_str})"
        elif command.operation == "UPDATE":
            data_str = self._format_data(command.data)
            return f"{firestore_ref}.update({data_str})"
        elif command.operation == "DELETE":
            return f"{firestore_ref}.delete()"
        else:
            return f"{firestore_ref}.{command.operation.lower()}(...)"


class VerboseConsoleDialect(ConsoleDialect):
    """Versión más detallada del dialecto de consola con análisis profundo"""
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Versión extra verbosa para debugging profundo"""
        if not commands:
            print("✅ No commands to execute")
            return
        
        # Análisis previo
        self._print_pre_analysis(commands)
        
        # Ejecutar comandos normalmente
        super().execute_commands(commands)
        
        # Post-análisis
        self._print_post_analysis(commands)
    
    def _print_pre_analysis(self, commands: List[AbstractCommand]) -> None:
        """Imprime análisis previo de los comandos"""
        operations = {}
        levels = {}
        paths = {}
        
        for cmd in commands:
            # Contar operaciones
            operations[cmd.operation] = operations.get(cmd.operation, 0) + 1
            
            # Contar niveles
            levels[cmd.level] = levels.get(cmd.level, 0) + 1
            
            # Analizar collections
            path_parts = cmd.entity_path.split('/')
            for i in range(0, len(path_parts), 2):
                if i < len(path_parts):
                    collection = path_parts[i]
                    paths[collection] = paths.get(collection, 0) + 1
        
        print(f"\n{'🔍 COMMAND ANALYSIS':=^80}")
        print(f"📊 Operations breakdown:")
        for op, count in sorted(operations.items()):
            emoji = {"CREATE": "➕", "UPDATE": "✏️", "DELETE": "🗑️"}.get(op, "🔄")
            print(f"   {emoji} {op}: {count} commands")
        
        print(f"\n📏 Hierarchy levels:")
        for level, count in sorted(levels.items()):
            indent = "  " * level
            print(f"   {indent}📁 Level {level}: {count} documents")
        
        print(f"\n🗂️ Collections affected:")
        for collection, count in sorted(paths.items()):
            print(f"   📋 {collection}: {count} operations")
        
        print(f"{'='*80}")
    
    def _print_post_analysis(self, commands: List[AbstractCommand]) -> None:
        """Imprime análisis posterior de los comandos"""
        if not commands:
            return
        
        operations = {}
        max_level = 0
        
        for cmd in commands:
            operations[cmd.operation] = operations.get(cmd.operation, 0) + 1
            max_level = max(max_level, cmd.level)
        
        print(f"{'📋 EXECUTION SUMMARY':=^80}")
        print(f"🎯 Execution strategy: {'Transactional' if self.transaction != '🚫 No Transaction' else 'Individual operations'}")
        print(f"🏗️ Architecture: Document hierarchy with {max_level + 1} levels")
        
        change_pattern = []
        for op, count in operations.items():
            emoji = {"CREATE": "➕", "UPDATE": "✏️", "DELETE": "🗑️"}.get(op, "🔄")
            change_pattern.append(f"{emoji}{count} {op.lower()}{'s' if count != 1 else ''}")
        
        print(f"🔄 Change pattern: {', '.join(change_pattern)}")
        print(f"⚡ Performance: {len(commands)} operations in single transaction")
        print(f"{'='*80}\n")
# ==================== PUBLIC API ====================

__all__ = [
    'ChangeType',
    'TrackedEntity', 
    'AbstractCommand',
    'DatabaseDialect',
    'FirestoreDialect',
    'ChangeTracker',
    'get_change_tracker',
    'set_change_tracker', 
    'clear_change_tracker'
]