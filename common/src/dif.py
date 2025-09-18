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


# Función auxiliar para mostrar los cambios de forma más legible
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

# Ejemplo de uso
def test_function():
    """
    Función de prueba para verificar que funciona correctamente
    """
    # Datos de ejemplo (como si fueran el resultado de model_dump())
    original = {
        "id": "user123",
        "name": "Juan Pérez",
        "email": "juan@email.com",
        "age": 30,
        "orders": [
            {
                "id": "order1",
                "total": 1251.98,
                "status": "pending",
                "items": [
                    {"id": "item1", "name": "Laptop", "price": 1200.00, "quantity": 1},
                    {"id": "item2", "name": "Mouse", "price": 25.99, "quantity": 2}
                ]
            },
            {
                "id": "order2",
                "total": 150.00,
                "status": "completed",
                "items": [
                    {"id": "item3", "name": "Keyboard", "price": 150.00, "quantity": 1}
                ]
            }
        ]
    }
    
    modified = {
        "id": "user123",
        "name": "Juan Pérez",
        "email": "juan.perez@newemail.com",  # Cambiado
        "age": 31,  # Cambiado
        "orders": [
            {
                "id": "order1",
                "total": 1300.50,  # Cambiado
                "status": "confirmed",  # Cambiado
                "items": [
                    {"id": "item1", "name": "Laptop", "price": 1250.00, "quantity": 1},  # precio cambiado
                    {"id": "item2", "name": "Mouse", "price": 25.99, "quantity": 3},     # cantidad cambiada
                    {"id": "item4", "name": "Monitor", "price": 300.00, "quantity": 1}   # item nuevo
                ]
            },
            # order2 eliminada, nueva orden añadida:
            {
                "id": "order3",
                "total": 200.00,
                "status": "pending",
                "items": [
                    {"id": "item5", "name": "Webcam", "price": 80.00, "quantity": 1},
                    {"id": "item6", "name": "Speakers", "price": 120.00, "quantity": 1}
                ]
            }
        ]
    }
    
    changes = analyze_changes(original, modified)
    print_changes(changes)
    return changes

if __name__ == "__main__":
    test_function()