from abc import ABC, abstractmethod
from contextvars import ContextVar
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from uuid import UUID
from deepdiff import DeepDiff
from common.infrastructure import Document,collection
from common.util import get_id,ID
from pydantic import BaseModel, Field
import json

class ChangeType(Enum):
    UNCHANGED = "unchanged"
    ADDED = "added" 
    MODIFIED = "modified"
    DELETED = "deleted"

class TrackedEntity:
    def __init__(self, entity_id: Any, state: ChangeType, document: Document, original_snapshot: Dict):
        self.entity_id = entity_id
        self.state = state
        self.current_document = document
        self.original_snapshot = original_snapshot  # Ahora es Dict, no Document
        self.entity_type = document.__class__.__name__

class ChangeTracker:
    def __init__(self):
        self._tracked_entities: Dict[Any, TrackedEntity] = {}
    
    def set_entity(self, document: Document, state: ChangeType) -> None:
        """Establece o actualiza el estado de una entidad con validaciones internas"""
        
        if not self.is_tracked(document):
            # Primera vez que se trackea - crear snapshot
            original_snapshot = self._create_snapshot(document)
            
            entity_data = TrackedEntity(
                entity_id=document.id,
                state=state,
                document=document,
                original_snapshot=original_snapshot,                
            )
            self._tracked_entities[document.id] = entity_data
            
        else:
            # Ya existe - validar transición y actualizar estado
            tracked = self._tracked_entities[document.id]
            
            if not self._is_valid_transition(tracked.state, state):
                raise ValueError(f"Invalid state transition: {tracked.state} → {state}")
                
            tracked.state = state
    
    def get_tracked_entity(self, document: Document) -> Optional[Document]:
        """Devuelve la instancia del Document trackeado"""
        tracked = self._tracked_entities.get(document.id)
        return tracked.current_document if tracked else None
        
    def is_tracked(self, document: Document) -> bool:
        return document.id in self._tracked_entities
    
    def save_changes(self) -> None:
        """Procesa todos los cambios trackeados e imprime información de debug"""
        print("=== PROCESANDO CAMBIOS ===")
        
        for entity_id, tracked_entity in self._tracked_entities.items():
            print(f"\nEntidad: {tracked_entity.entity_type}")
            print(f"ID: {entity_id}")
            print(f"Estado: {tracked_entity.state.value}")
            
            if tracked_entity.state == ChangeType.MODIFIED:
                # Obtener los datos serializados
                original_data = tracked_entity.original_snapshot  # Ya es Dict
                current_data = self._create_snapshot(tracked_entity.current_document)

                changes = analyze_changes(
                    original_data, 
                    current_data
                )
    
                
                print("Diferencias detectadas:")
                if changes['fields_changed'] or changes['lists_changed']:
                    print_changes(changes)
                else:
                    print("  No se detectaron cambios")
                
            print("-" * 40)
    
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
        return document.model_dump()    
    def _analyze_changes(self,original, current, path="root"):
        """
        Compara dos estructuras dict/list/valores escalares
        y devuelve un dict con los cambios detectados.
        """
        result = {"fields_changed": {}, "lists_changed": {}}

        # Caso 1: tipos distintos → cambio directo
        if type(original) != type(current):
            result["fields_changed"][path] = {
                "old_value": original,
                "new_value": current,
            }
            return result

        # Caso 2: dict
        if isinstance(original, dict):
            for key in set(original.keys()) | set(current.keys()):
                if key == "id":  # ignoramos id
                    continue
                new_path = f"{path}.{key}" if path != "root" else key

                if key not in original:
                    result["fields_changed"][new_path] = {
                        "old_value": None,
                        "new_value": current[key],
                    }
                elif key not in current:
                    result["fields_changed"][new_path] = {
                        "old_value": original[key],
                        "new_value": None,
                    }
                else:
                    sub = self._analyze_changes(original[key], current[key], new_path)
                    result["fields_changed"].update(sub["fields_changed"])
                    result["lists_changed"].update(sub["lists_changed"])

            return result

        # Caso 3: list
        if isinstance(original, list):
            # si son listas de dict con id → diff por id
            if (
                (original and isinstance(original[0], dict) and "id" in original[0])
                or (current and isinstance(current[0], dict) and "id" in current[0])
            ):
                orig_by_id = {o["id"]: o for o in original if isinstance(o, dict) and "id" in o}
                curr_by_id = {c["id"]: c for c in current if isinstance(c, dict) and "id" in c}

                added = [curr_by_id[i] for i in curr_by_id.keys() - orig_by_id.keys()]
                removed = [orig_by_id[i] for i in orig_by_id.keys() - curr_by_id.keys()]

                modified = []
                for i in orig_by_id.keys() & curr_by_id.keys():
                    sub = self._analyze_changes(orig_by_id[i], curr_by_id[i], f"{path}[{i}]")
                    if sub["fields_changed"] or sub["lists_changed"]:
                        modified.append({"id": i, "changes": sub})

                if added or removed or modified:
                    result["lists_changed"][path] = {
                        "added": added,
                        "removed": removed,
                        "modified": modified,
                    }
            else:
                # listas simples: comparar completas
                if original != current:
                    result["fields_changed"][path] = {
                        "old_value": original,
                        "new_value": current,
                    }

            return result

        # Caso 4: valor escalar
        if original != current:
            result["fields_changed"][path] = {
                "old_value": original,
                "new_value": current,
            }

        return result

    def _print_custom_changes(self, changes: Dict) -> None:
        """Imprime los cambios de forma legible"""
        
        if changes['fields_changed']:
            print("  CAMPOS CAMBIADOS:")
            for path, change in changes['fields_changed'].items():
                print(f"    {path}: {change['old_value']} → {change['new_value']}")
        
        if changes['lists_changed']:
            print("  LISTAS CAMBIADAS:")
            for path, list_change in changes['lists_changed'].items():
                print(f"    {path}:")
                
                if list_change['added']:
                    print(f"      AGREGADOS ({len(list_change['added'])}):")
                    for item in list_change['added']:
                        print(f"        - ID: {item['id']}")
                
                if list_change['removed']:
                    print(f"      ELIMINADOS ({len(list_change['removed'])}):")
                    for item in list_change['removed']:
                        print(f"        - ID: {item['id']}")
                
                if list_change.get('modified'):
                    print(f"      MODIFICADOS ({len(list_change['modified'])}):")
                    for mod in list_change['modified']:
                        print(f"        - ID: {mod['id']} (cambios internos)")    
    
    def clear(self) -> None:
        """Limpia el tracking (al cerrar transacción)"""
        self._tracked_entities.clear()
def analyze_changes(original, current):
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
            
            # Obtener todas las claves (menos id)
            all_keys = (set(orig.keys()) | set(curr.keys())) - {"id"}
            
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
    #id:str = Field(default_factory=lambda:str(get_id()))
    name: str
    price: float
    quantity: int

class Order(Document):
    #id:str = Field(default_factory=lambda:str(get_id()))
    total: float
    status: str
    items: List[Item] = collection()

class User(Document):
    #id:str = Field(default_factory=lambda:str(get_id()))
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
    item1 = Item( name="Laptop", price=1200.00, quantity=1)
    item2 = Item( name="Mouse", price=25.99, quantity=2)
    
    # 2. Crear orden con items
    order1 = Order( total=1251.98, status="pending", items=[item1, item2])
    
    # 3. Crear otro item y orden
    item3 = Item(name="Keyboard", price=150.00, quantity=1)
    order2 = Order(total=150.00, status="completed", items=[item3])
    
    # 4. Crear usuario con órdenes
    user = User(        
        name="Juan Pérez", 
        email="juan@email.com", 
        age=30,
        orders=[order1, order2]
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
    user.orders[0].items[1].quantity = 3     # Más ratones
    
    # Agregar nuevo item a orden existente
    new_item = Item(name="Monitor", price=300.00, quantity=1)
    user.orders[0].items.append(new_item)
    
    # Agregar nueva orden completa
    item4 = Item( name="Webcam", price=80.00, quantity=1)
    item5 = Item( name="Speakers", price=120.00, quantity=1)
    new_order = Order( total=200.00, status="pending", items=[item4, item5])
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
        print(f"Orden {i+1}: {len(order.items)} items, total: {order.total}, status: {order.status}")
    
    print("\n")
    
    # Procesar cambios - aquí veremos el algoritmo personalizado en acción
    tracker.save_changes()


if __name__ == "__main__":
    test_change_tracker()