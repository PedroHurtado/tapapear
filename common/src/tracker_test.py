from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, ConfigDict
from common.infrastructure import Document, collection


class ChangeType(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added" 
    MODIFIED = "modified"
    DELETED = "deleted"


class OperationType(Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


# ==================== DATA CLASSES (Pydantic Frozen) ====================

class TrackedEntity(BaseModel):
    entity_id: Any
    state: ChangeType
    current_document: Document
    original_snapshot: Dict
    entity_type: str
    
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)


class AbstractCommand(BaseModel):
    """Comando abstracto independiente de base de datos"""
    operation: OperationType
    entity_path: str
    data: Dict[str, Any]
    level: int = 0
    parent_id: Optional[Any] = None
    
    model_config = ConfigDict(frozen=True)
    
    def __repr__(self):
        return f"AbstractCommand(operation={self.operation.value}, path={self.entity_path}, level={self.level})"


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
    
    @abstractmethod
    def sort_commands(self, commands: List[AbstractCommand], change_type: ChangeType) -> List[AbstractCommand]:
        """Ordena los comandos según las reglas específicas de la base de datos"""
        pass


# ==================== CHANGE TRACKER MEJORADO ====================

class ChangeTracker:
    def __init__(self, dialect: DatabaseDialect):
        self._tracked_entities: Dict[Any, TrackedEntity] = {}
        self.dialect = dialect
    
    def set_entity(self, document: Document, state: ChangeType) -> None:
        """Establece o actualiza el estado de una entidad con validaciones internas"""
        
        if not self.is_tracked(document):
            # Primera vez que se trackea - crear snapshot
            original_snapshot = self._create_snapshot(document)
            
            entity_data = TrackedEntity(
                entity_id=document.id,
                state=state,
                current_document=document,
                original_snapshot=original_snapshot,
                entity_type=document.__class__.__name__
            )
            self._tracked_entities[document.id] = entity_data
            
        else:
            # Ya existe - validar transición y actualizar estado
            tracked = self._tracked_entities[document.id]
            
            if not self._is_valid_transition(tracked.state, state):
                raise ValueError(f"Invalid state transition: {tracked.state} → {state}")
            
            # Crear nueva instancia frozen con estado actualizado
            updated_entity = tracked.model_copy(update={'state': state})
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
            
            # Delegar el ordenamiento al dialect específico
            if entity_commands:
                sorted_commands = self.dialect.sort_commands(entity_commands, tracked_entity.state)
                self.dialect.execute_commands(sorted_commands)
    
    def _generate_create_commands(self, tracked_entity: TrackedEntity) -> List[AbstractCommand]:
        """Genera comandos CREATE recursivos para toda la estructura"""
        commands = []
        snapshot = tracked_entity.original_snapshot
        
        # Recorrer recursivamente toda la estructura y generar comandos CREATE/DELETE
        # (mismo algoritmo, solo cambia el OperationType)
        self._generate_recursive_commands(
            data=snapshot,
            parent_path="",
            parent_id=None,
            level=0,
            commands=commands,
            operation=OperationType.CREATE
        )
        
        return commands
    
    def _generate_recursive_create_commands(self, data: Dict, parent_path: str, 
                                          parent_id: Any, level: int, commands: List[AbstractCommand]):
        """Genera comandos CREATE de forma recursiva"""
        
        # 1. Comando para crear el documento actual
        entity_type = data.get('__class__', 'document').lower()
        entity_id = data.get('id')
        
        if not entity_id:
            return
        
        # Construir el path del documento
        if level == 0:
            # Documento raíz
            document_path = f"{entity_type}s"
        else:
            # Documento anidado (subcollection)
            document_path = f"{parent_path}/{entity_type}s"
        
        # Filtrar datos para el comando (sin collections)
        command_data = self._filter_command_data(data)
        
        command = AbstractCommand(
            operation=OperationType.CREATE,
            entity_path=document_path,
            data=command_data,
            level=level,
            parent_id=parent_id
        )
        commands.append(command)
        
        print(f"CREATE Command: {command}")
        
        # 2. Procesar collections (documentos anidados)
        current_document_path = f"{document_path}/{entity_id}"
        
        for field_name, field_value in data.items():
            if self._is_collection_field(field_name, field_value):
                # Es una collection - procesar cada documento
                if isinstance(field_value, list):
                    for nested_doc in field_value:
                        if isinstance(nested_doc, dict) and 'id' in nested_doc:
                            self._generate_recursive_create_commands(
                                data=nested_doc,
                                parent_path=current_document_path,
                                parent_id=entity_id,
                                level=level + 1,
                                commands=commands
                            )
    
    def _generate_delete_commands(self, tracked_entity: TrackedEntity) -> List[AbstractCommand]:
        """Genera comandos DELETE recursivos para toda la estructura"""
        commands = []
        snapshot = tracked_entity.original_snapshot
        
        # Mismo algoritmo que CREATE, solo cambia el OperationType
        # El dialect se encarga de ordenar correctamente
        self._generate_recursive_commands(
            data=snapshot,
            parent_path="",
            parent_id=None,
            level=0,
            commands=commands,
            operation=OperationType.DELETE
        )
        
        return commands
    
    def _generate_recursive_delete_commands(self, data: Dict, parent_path: str, 
                                          parent_id: Any, level: int, commands: List[AbstractCommand]):
        """Genera comandos DELETE de forma recursiva"""
        
        entity_type = data.get('__class__', 'document').lower()
        entity_id = data.get('id')
        
        if not entity_id:
            return
        
        # Construir el path del documento
        if level == 0:
            document_path = f"{entity_type}s/{entity_id}"
        else:
            document_path = f"{parent_path}/{entity_type}s/{entity_id}"
        
        # 1. Primero procesar collections (documentos anidados) - DELETE profundo primero
        for field_name, field_value in data.items():
            if self._is_collection_field(field_name, field_value):
                if isinstance(field_value, list):
                    for nested_doc in field_value:
                        if isinstance(nested_doc, dict) and 'id' in nested_doc:
                            self._generate_recursive_delete_commands(
                                data=nested_doc,
                                parent_path=document_path,
                                parent_id=entity_id,
                                level=level + 1,
                                commands=commands
                            )
        
        # 2. Después crear el comando DELETE para este documento
        command = AbstractCommand(
            operation=OperationType.DELETE,
            entity_path=document_path,
            data={},  # DELETE no necesita data
            level=level,
            parent_id=parent_id
        )
        commands.append(command)
        
        print(f"DELETE Command: {command}")
    
    def _generate_update_commands(self, tracked_entity: TrackedEntity) -> List[AbstractCommand]:
        """Genera comandos UPDATE/CREATE/DELETE para una entidad modificada"""
        commands = []
        
        # Analizar diferencias
        changes = self._diff(tracked_entity.original_snapshot, 
                           self._create_snapshot(tracked_entity.current_document))
        
        # Procesar cambios en campos simples
        if changes["fields_changed"]:
            update_data = {}
            for field_path, change in changes["fields_changed"].items():
                if not self._is_nested_list_field(field_path):
                    update_data[field_path] = change["new_value"]
            
            if update_data:
                command = AbstractCommand(
                    operation=OperationType.UPDATE,
                    entity_path=f"{tracked_entity.entity_type.lower()}s/{tracked_entity.entity_id}",
                    data=update_data,
                    level=0,
                    parent_id=tracked_entity.entity_id
                )
                commands.append(command)
        
        # Procesar cambios en listas
        if changes["lists_changed"]:
            commands.extend(self._generate_list_commands(
                changes["lists_changed"], 
                tracked_entity.entity_id,
                tracked_entity.entity_type
            ))
        
        return commands
    
    def _generate_list_commands(self, lists_changes: Dict, parent_id: Any, parent_type: str) -> List[AbstractCommand]:
        """Genera comandos para cambios en listas"""
        commands = []
        
        for list_path, changes in lists_changes.items():
            # Items añadidos - usar el nuevo algoritmo recursivo
            for added_item in changes.get("added", []):
                if isinstance(added_item, dict) and 'id' in added_item:
                    # Usar el generador recursivo para CREATE
                    parent_path = f"{parent_type.lower()}s/{parent_id}"
                    self._generate_recursive_create_commands(
                        data=added_item,
                        parent_path=parent_path,
                        parent_id=parent_id,
                        level=1,
                        commands=commands
                    )
            
            # Items eliminados - usar el nuevo algoritmo recursivo  
            for removed_item in changes.get("removed", []):
                if isinstance(removed_item, dict) and 'id' in removed_item:
                    # Usar el generador recursivo para DELETE
                    parent_path = f"{parent_type.lower()}s/{parent_id}"
                    self._generate_recursive_delete_commands(
                        data=removed_item,
                        parent_path=parent_path,
                        parent_id=parent_id,
                        level=1,
                        commands=commands
                    )
            
            # Items modificados
            for modified_item in changes.get("modified", []):
                item_id = modified_item["id"]
                item_changes = modified_item["changes"]
                
                # Generar UPDATE para campos simples del item
                if item_changes.get("fields_changed"):
                    update_data = {}
                    for field_path, change in item_changes["fields_changed"].items():
                        update_data[field_path] = change["new_value"]
                    
                    command = AbstractCommand(
                        operation=OperationType.UPDATE,
                        entity_path=f"{list_path.split('.')[-1]}/{item_id}",
                        data=update_data,
                        level=1,
                        parent_id=parent_id
                    )
                    commands.append(command)
        
        return commands
    
    def _filter_command_data(self, data: Dict) -> Dict:
        """Filtra los datos para el comando, removiendo collections y metadata"""
        filtered_data = {}
        
        for key, value in data.items():
            # Excluir campos especiales
            if key.startswith('__'):
                continue
            
            # Excluir collections (listas de documentos)
            if self._is_collection_field(key, value):
                continue
                
            # Incluir el resto
            filtered_data[key] = value
            
        return filtered_data
    
    def _is_collection_field(self, field_name: str, field_value: Any) -> bool:
        """Determina si un campo es una collection (lista de documentos)"""
        if not isinstance(field_value, list):
            return False
            
        # Si la lista está vacía, asumir que no es collection
        if not field_value:
            return False
            
        # Verificar si el primer elemento es un documento (tiene id)
        first_item = field_value[0]
        return isinstance(first_item, dict) and 'id' in first_item
    
    def _is_nested_list_field(self, field_path: str) -> bool:
        """Verifica si un campo pertenece a una lista anidada"""
        return "[id=" in field_path
    
    def _is_valid_transition(self, current_state: ChangeType, new_state: ChangeType) -> bool:
        """Valida si una transición de estado es permitida"""
        valid_transitions = {
            ChangeType.UNCHANGED: [ChangeType.MODIFIED, ChangeType.DELETED],
            ChangeType.MODIFIED: [],   # No puede cambiar a ningún estado
            ChangeType.ADDED: [],      # No puede cambiar a ningún estado  
            ChangeType.DELETED: []     # No puede cambiar a ningún estado
        }
        return new_state in valid_transitions.get(current_state, [])
    
    def _create_snapshot(self, document: Document) -> Dict:
        """Crea una copia del documento usando model_dump"""
        snapshot = document.model_dump()
        # Agregar el tipo de clase para poder identificar el tipo en los comandos
        snapshot['__class__'] = document.__class__.__name__
        return snapshot
    
    def _diff(self, original, current, path="root"):
        """
        Compara dos estructuras dict/list/valores escalares y devuelve un dict con cambios:
            {
                "fields_changed": {...},
                "lists_changed": {...}
            }
        """
        
        def _compare(orig, curr, path):
            # Casos donde uno es None
            if orig is None and curr is None:
                return {"fields_changed": {}, "lists_changed": {}}
            
            if orig is None and curr is not None:
                return {"fields_changed": {path: {"old_value": None, "new_value": curr}}, "lists_changed": {}}
            
            if orig is not None and curr is None:
                return {"fields_changed": {path: {"old_value": orig, "new_value": None}}, "lists_changed": {}}
            
            # Tipos distintos
            if type(orig) != type(curr):
                return {"fields_changed": {path: {"old_value": orig, "new_value": curr}}, "lists_changed": {}}

            # Escalar (valores primitivos)
            if not isinstance(orig, (dict, list)):
                if orig != curr:
                    return {"fields_changed": {path: {"old_value": orig, "new_value": curr}}, "lists_changed": {}}
                return {"fields_changed": {}, "lists_changed": {}}

            # Dict
            if isinstance(orig, dict):
                fields_changed = {}
                lists_changed = {}
                
                # Obtener todas las claves (menos id y __class__)
                all_keys = (set(orig.keys()) | set(curr.keys())) - {"id", "__class__"}
                
                for key in all_keys:
                    new_path = f"{path}.{key}" if path != "root" else key
                    
                    if key not in orig:
                        # Campo añadido
                        fields_changed[new_path] = {"old_value": None, "new_value": curr[key]}
                    elif key not in curr:
                        # Campo eliminado
                        fields_changed[new_path] = {"old_value": orig[key], "new_value": None}
                    else:
                        # Campo existe en ambos - comparar recursivamente
                        sub_result = _compare(orig[key], curr[key], new_path)
                        fields_changed.update(sub_result["fields_changed"])
                        lists_changed.update(sub_result["lists_changed"])
                
                return {"fields_changed": fields_changed, "lists_changed": lists_changed}

            # List
            if isinstance(orig, list):
                # Verificar si es una lista vacía
                if not orig and not curr:
                    return {"fields_changed": {}, "lists_changed": {}}
                
                # Verificar si es una lista de dicts con id
                is_list_with_ids = False
                if orig and isinstance(orig[0], dict) and "id" in orig[0]:
                    is_list_with_ids = True
                elif curr and isinstance(curr[0], dict) and "id" in curr[0]:
                    is_list_with_ids = True
                
                if is_list_with_ids:
                    # Lista de objetos con ID
                    orig_by_id = {x["id"]: x for x in orig if isinstance(x, dict) and "id" in x}
                    curr_by_id = {x["id"]: x for x in curr if isinstance(x, dict) and "id" in x}

                    added = []
                    removed = []
                    modified = []

                    # Elementos añadidos
                    for item_id in curr_by_id.keys() - orig_by_id.keys():
                        added.append(curr_by_id[item_id])

                    # Elementos eliminados
                    for item_id in orig_by_id.keys() - curr_by_id.keys():
                        removed.append(orig_by_id[item_id])

                    # Elementos modificados
                    fields_changed = {}
                    lists_changed = {}
                    
                    for item_id in orig_by_id.keys() & curr_by_id.keys():
                        item_path = f"{path}[id={item_id}]"
                        sub_result = _compare(orig_by_id[item_id], curr_by_id[item_id], item_path)
                        
                        # Si hay cambios en este item, agregarlo a modified
                        if sub_result["fields_changed"] or sub_result["lists_changed"]:
                            modified.append({
                                "id": item_id,
                                "changes": sub_result
                            })
                        
                        # También propagar los cambios de campos individuales
                        fields_changed.update(sub_result["fields_changed"])
                        lists_changed.update(sub_result["lists_changed"])

                    # Agregar información de la lista si hay cambios estructurales
                    result = {"fields_changed": fields_changed, "lists_changed": lists_changed}
                    
                    if added or removed or modified:
                        result["lists_changed"][path] = {
                            "added": added,
                            "removed": removed,
                            "modified": modified
                        }
                    
                    return result
                else:
                    # Lista simple (sin IDs)
                    if orig != curr:
                        return {"fields_changed": {path: {"old_value": orig, "new_value": curr}}, "lists_changed": {}}
                    return {"fields_changed": {}, "lists_changed": {}}

        # Ejecutar la comparación
        result = _compare(original, current, "root")
        return result

    def clear(self) -> None:
        """Limpia el tracking (al cerrar transacción)"""
        self._tracked_entities.clear()


# =============================================================================
# EJEMPLO DE DIALECT PARA DEMOSTRAR EL ORDEN
# =============================================================================


class MockFirestoreDialect(DatabaseDialect):
    """Mock dialect para demostrar el funcionamiento"""

    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        print(f"\n=== EJECUTANDO {len(commands)} COMANDOS ===")
        for i, cmd in enumerate(commands, 1):
            print(f"{i}. {cmd.operation.value} {cmd.entity_path} (level={cmd.level})")
            if cmd.data:
                print(f"   Data: {cmd.data}")

    def sort_commands(
        self, commands: List[AbstractCommand], change_type: ChangeType
    ) -> List[AbstractCommand]:
        """Ordena los comandos según las reglas de Firestore"""
        if change_type == ChangeType.ADDED:
            # Para CREATE: primero padres (level bajo), luego hijos (level alto)
            return sorted(commands, key=lambda cmd: cmd.level)
        elif change_type == ChangeType.DELETED:
            # Para DELETE: primero hijos (level alto), luego padres (level bajo)
            return sorted(commands, key=lambda cmd: -cmd.level)
        else:
            # Para UPDATE: mantener orden original
            return commands


def print_changes(changes):
    """
    Muestra los cambios de forma legible
    """
    print("=== CAMBIOS DETECTADOS ===")

    if changes["fields_changed"]:
        print("\n📝 CAMPOS MODIFICADOS:")
        for path, change in changes["fields_changed"].items():
            old_val = change["old_value"]
            new_val = change["new_value"]

            if old_val is None:
                print(f"  ➕ {path}: AÑADIDO = {new_val}")
            elif new_val is None:
                print(f"  ➖ {path}: ELIMINADO = {old_val}")
            else:
                print(f"  🔄 {path}: {old_val} → {new_val}")

    if changes["lists_changed"]:
        print("\n📋 LISTAS MODIFICADAS:")
        for path, list_changes in changes["lists_changed"].items():
            print(f"  Lista: {path}")

            if list_changes.get("added"):
                print(f"    ➕ Añadidos: {len(list_changes['added'])} elementos")
                for item in list_changes["added"]:
                    if isinstance(item, dict) and "id" in item:
                        print(f"      - ID: {item['id']}")

            if list_changes.get("removed"):
                print(f"    ➖ Eliminados: {len(list_changes['removed'])} elementos")
                for item in list_changes["removed"]:
                    if isinstance(item, dict) and "id" in item:
                        print(f"      - ID: {item['id']}")

            if list_changes.get("modified"):
                print(f"    🔄 Modificados: {len(list_changes['modified'])} elementos")
                for item in list_changes["modified"]:
                    print(f"      - ID: {item['id']}")


# =============================================================================
# ENTIDADES DE EJEMPLO PARA PRUEBAS
# =============================================================================


class Item(Document):
    
    name: str
    price: float
    quantity: int


class Order(Document):
    
    total: float
    status: str
    items: List[Item] = collection()


class User(Document):
    
    name: str
    email: str
    age: int
    orders: List[Order] = collection()


# =============================================================================
# EJEMPLOS DE USO
# =============================================================================


def test_change_tracker():
    """Ejemplo de uso del ChangeTracker con estructuras anidadas"""

    # Crear ChangeTracker
    tracker = ChangeTracker()

    print("=== CREANDO ESTRUCTURA ANIDADA ===")

    # 1. Crear items
    item1 = Item(name="Laptop", price=1200.00, quantity=1)
    item2 = Item(name="Mouse", price=25.99, quantity=2)

    # 2. Crear orden con items
    order1 = Order(total=1251.98, status="pending", items=[item1, item2])

    # 3. Crear otro item y orden
    item3 = Item(name="Keyboard", price=150.00, quantity=1)
    order2 = Order(total=150.00, status="completed", items=[item3])

    # 4. Crear usuario con órdenes
    user = User(
        name="Juan Pérez", email="juan@email.com", age=30, orders=[order1, order2]
    )

    # Trackear el usuario como UNCHANGED (simulando lectura de BD)
    tracker.set_entity(user, ChangeType.UNCHANGED)
    print(f"Usuario {user.name} creado con {len(user.orders)} órdenes")
    print(f"Orden 1: {len(order1.items)} items, total: {order1.total}")
    print(f"Orden 2: {len(order2.items)} items, total: {order2.total}")

    print("\n=== REALIZANDO MODIFICACIONES ===")

    # 5. Modificaciones complejas
    print("Modificando usuario...")

    # Cambiar datos del usuario
    user.age = 31
    user.email = "juan.perez@newemail.com"

    # Modificar orden existente
    user.orders[0].status = "confirmed"
    user.orders[0].total = 1300.50  # Nuevo total

    # Modificar item existente
    user.orders[0].items[0].price = 1250.00  # Nuevo precio laptop
    user.orders[0].items[1].quantity = 3  # Más ratones

    # Agregar nuevo item a orden existente
    new_item = Item(name="Monitor", price=300.00, quantity=1)
    user.orders[0].items.append(new_item)

    # Agregar nueva orden completa
    item4 = Item(name="Webcam", price=80.00, quantity=1)
    item5 = Item(name="Speakers", price=120.00, quantity=1)
    new_order = Order(total=200.00, status="pending", items=[item4, item5])
    user.orders.append(new_order)

    # Eliminar una orden (la segunda original)
    user.orders.pop(1)  # Elimina la orden del keyboard

    print("Modificaciones realizadas:")
    print("- Cambié edad y email del usuario")
    print("- Cambié status y total de la primera orden")
    print("- Cambié precio del laptop y cantidad de ratones")
    print("- Agregué un monitor a la primera orden")
    print("- Agregué una nueva orden con webcam y speakers")
    print("- Eliminé la orden del keyboard")

    # Marcar como modificado
    tracker.set_entity(user, ChangeType.MODIFIED)

    print(f"\nUsuario ahora tiene {len(user.orders)} órdenes")
    for i, order in enumerate(user.orders):
        print(
            f"Orden {i+1}: {len(order.items)} items, total: {order.total}, status: {order.status}"
        )

    print("\n")

    # Procesar cambios - aquí veremos el algoritmo personalizado en acción
    tracker.save_changes()


if __name__ == "__main__":
    test_change_tracker()
