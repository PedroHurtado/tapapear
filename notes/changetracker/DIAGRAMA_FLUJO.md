# 🎨 DIAGRAMA DE FLUJO - Modificación ADD Operation

## 📊 Flujo ANTES de la Modificación

```
┌─────────────────────────────────────────────────────────┐
│  tracker.set_entity(store, ChangeType.ADDED)           │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   Crear TrackedEntity      │
         │   - state: ADDED           │
         │   - original_snapshot ❌   │
         └────────────┬───────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   tracker.save_changes()   │
         └────────────┬───────────────┘
                      │
                      ▼
    ┌─────────────────────────────────────┐
    │  _generate_create_commands()        │
    │                                     │
    │  snapshot = original_snapshot ❌    │
    │  (sin filtrar None values)          │
    └────────────┬────────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────────┐
    │  _generate_recursive_commands()     │
    │                                     │
    │  Procesa snapshot con None ❌       │
    └────────────┬────────────────────────┘
                 │
                 ▼
         ┌───────────────────┐
         │  AbstractCommand  │
         │                   │
         │  data: {          │
         │    name: "Store"  │
         │    description:   │
         │      null ❌      │
         │    ...            │
         │  }                │
         └───────────────────┘
```

## 📊 Flujo DESPUÉS de la Modificación

```
┌─────────────────────────────────────────────────────────┐
│  tracker.set_entity(store, ChangeType.ADDED)           │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   Crear TrackedEntity      │
         │   - state: ADDED           │
         │   - current_document ✅    │
         └────────────┬───────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   tracker.save_changes()   │
         └────────────┬───────────────┘
                      │
                      ▼
    ┌─────────────────────────────────────────┐
    │  _generate_create_commands()            │
    │                                         │
    │  current_snapshot =                     │
    │    _create_snapshot(current_document) ✅│
    │                                         │
    │  filtered_snapshot =                    │
    │    _filter_none_recursive(snapshot) ✅  │
    └────────────┬────────────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────────────┐
    │  _filter_none_recursive()               │
    │                                         │
    │  Procesa recursivamente:                │
    │  • Dicts: excluye keys con None         │
    │  • Lists: filtra items None             │
    │  • Preserva objetos especiales          │
    └────────────┬────────────────────────────┘
                 │
                 ▼
    ┌─────────────────────────────────────────┐
    │  _generate_recursive_commands()         │
    │                                         │
    │  Procesa snapshot FILTRADO ✅           │
    └────────────┬────────────────────────────┘
                 │
                 ▼
         ┌───────────────────┐
         │  AbstractCommand  │
         │                   │
         │  data: {          │
         │    name: "Store"  │
         │    location: {...}│
         │    ✅ description │
         │       no aparece  │
         │  }                │
         └───────────────────┘
```

## 🔍 Comparación de Datos

### Estructura de Entrada
```python
Store(
    name="TechStore",
    description=None,      # ❌ Campo opcional sin valor
    location=(40.0, -3.0),
    products=[
        Product(
            name="Laptop",
            description=None,  # ❌ Campo opcional sin valor
            price=999.99,
            status=ACTIVE
        )
    ]
)
```

### ANTES - Comando Generado
```json
{
  "Store": {
    "data": {
      "name": "TechStore",
      "description": null,     // ❌ PROBLEMA
      "location": {
        "latitude": 40.0,
        "longitude": -3.0
      }
    }
  },
  "Product": {
    "data": {
      "name": "Laptop",
      "description": null,     // ❌ PROBLEMA
      "price": 999.99,
      "status": "active"
    }
  }
}
```

### DESPUÉS - Comando Generado
```json
{
  "Store": {
    "data": {
      "name": "TechStore",
      // ✅ description no aparece
      "location": {
        "latitude": 40.0,
        "longitude": -3.0
      }
    }
  },
  "Product": {
    "data": {
      "name": "Laptop",
      // ✅ description no aparece
      "price": 999.99,
      "status": "active"
    }
  }
}
```

## 🔄 Algoritmo de Filtrado

```
_filter_none_recursive(data):
    │
    ├─ Si data es None
    │   └─→ return None
    │
    ├─ Si data es Dict
    │   └─→ Para cada (key, value):
    │       ├─ Si value es None
    │       │   └─→ ❌ EXCLUIR del resultado
    │       └─ Si value no es None
    │           └─→ ✅ Incluir: result[key] = _filter_none_recursive(value)
    │
    ├─ Si data es List
    │   └─→ Para cada item:
    │       ├─ Si item es None
    │       │   └─→ ❌ EXCLUIR del resultado
    │       └─ Si item no es None
    │           └─→ ✅ Incluir: result.append(_filter_none_recursive(item))
    │
    └─ Si data es Objeto Especial
        └─→ ✅ return data (sin modificar)
            Ejemplos:
            • DocumentId
            • CollectionReference
            • GeoPointValue
```

## 📈 Impacto en Jerarquía de Comandos

```
Level 0: Store
    │
    ├─ ANTES: 5 campos (incluyendo description=null)
    └─ DESPUÉS: 4 campos (description excluido)

Level 1: Product  
    │
    ├─ ANTES: 6 campos (incluyendo description=null, coordinates=null)
    └─ DESPUÉS: 4 campos (ambos excluidos)

Level 1: Category
    │
    ├─ ANTES: 3 campos (incluyendo description=null)
    └─ DESPUÉS: 2 campos (description excluido)

Level 2: Tag
    │
    ├─ ANTES: 3 campos (incluyendo color=null)
    └─ DESPUÉS: 2 campos (color excluido)
```

## 🎯 Casos de Uso Soportados

```
✅ Caso 1: Todos los campos con valor
   → Todos aparecen en el comando

✅ Caso 2: Todos los campos None  
   → Solo campos obligatorios aparecen

✅ Caso 3: Mix de valores y None
   → Solo campos con valor aparecen

✅ Caso 4: Collections vacías
   → Array vacío []

✅ Caso 5: Collections con items None
   → Items filtrados

✅ Caso 6: Objetos especiales (GeoPoint, DocumentId)
   → Preservados sin cambios
```

## 📊 Métricas de Mejora

```
Reducción de Tamaño de Comandos:
┌──────────────────┬─────────┬──────────┬──────────┐
│ Escenario        │ Antes   │ Después  │ Reducción│
├──────────────────┼─────────┼──────────┼──────────┤
│ 1 campo None     │ 100%    │ 90%      │ -10%     │
│ 3 campos None    │ 100%    │ 70%      │ -30%     │
│ 50% None         │ 100%    │ 50%      │ -50%     │
└──────────────────┴─────────┴──────────┴──────────┘

Comandos más limpios = Mejor performance + Menor storage
```

---

**Visualización creada para entender el flujo de modificación**
