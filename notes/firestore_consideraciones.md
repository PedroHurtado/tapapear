# Operaciones en Firestore con Python

## Operaciones de Escritura Básicas

### `set()`
- Crea un documento nuevo o sobrescribe completamente uno existente
- Reemplaza todos los campos del documento
- Si el documento no existe, lo crea

### `set()` con `merge=True`
- Actualiza solo los campos especificados sin sobrescribir el documento completo
- Si el documento no existe, lo crea con los campos proporcionados
- Mantiene los campos existentes que no se especifican en la operación

### `update()`
- Actualiza campos específicos de un documento existente
- Falla si el documento no existe
- Permite usar dot notation para campos anidados (`"user.name"`)

## Operaciones Especiales para Arrays

### `ArrayUnion()`
- Añade elementos a un array solo si no existen ya
- Evita duplicados automáticamente
- Útil para listas de IDs, tags, etc.

```python
doc_ref.update({
    "tags": firestore.ArrayUnion(["python", "firebase"])
})
```

### `ArrayRemove()`
- Elimina todas las instancias de los elementos especificados del array
- Funciona por valor exacto, no por índice

```python
doc_ref.update({
    "tags": firestore.ArrayRemove(["javascript"])
})
```

### Arrays con Duplicados
**Limitación importante**: `ArrayUnion` NO permite duplicados.

Para arrays con duplicados necesitas:
```python
# Lectura, modificación, escritura manual
current_doc = doc_ref.get().to_dict()
current_array = current_doc.get("tags", [])
current_array.append("python")  # Permite duplicados
doc_ref.update({"tags": current_array})
```

## Valores Especiales del Servidor

### `firestore.DELETE_FIELD`
- Elimina completamente un campo del documento
- El campo desaparece del documento

```python
doc_ref.update({
    "campo_a_eliminar": firestore.DELETE_FIELD
})
```

### `firestore.SERVER_TIMESTAMP`
- Establece el timestamp del servidor en el momento de la escritura
- Garantiza consistencia temporal independiente del cliente

```python
doc_ref.update({
    "updated_at": firestore.SERVER_TIMESTAMP
})
```

### `firestore.Increment()`
- Incrementa/decrementa valores numéricos atómicamente

```python
doc_ref.update({
    "counter": firestore.Increment(1)
})
```

### `firestore.GeoPoint()`
- Tipo de dato especial para coordenadas geográficas (latitud, longitud)
- Permite consultas geoespaciales eficientes
- Latitud: -90 a 90, Longitud: -180 a 180

```python
from google.cloud.firestore import GeoPoint

# Crear un GeoPoint
location = GeoPoint(latitude=40.4168, longitude=-3.7038)  # Madrid

doc_ref.update({
    "location": location
})

# En un map también funciona
doc_ref.update({
    "user.address.coordinates": GeoPoint(40.4168, -3.7038)
})
```

#### Consultas con GeoPoint
Firestore no tiene consultas de distancia nativas, pero puedes:
- Ordenar por proximidad a un punto
- Usar bibliotecas como `geohash` para consultas de área
- Filtrar por rangos de latitud/longitud para área rectangular

## Maps en Firestore

Los **maps** son objetos anidados similares a:
- Value Objects en DDD
- Diccionarios en Python  
- DataClasses o modelos Pydantic

### Estructura Básica
```python
user_data = {
    "user": {
        "name": "Juan",
        "age": 30,
        "address": {
            "street": "Calle Mayor 123",
            "city": "Madrid",
            "postal_code": "28001"
        }
    }
}
```

### Operaciones en Maps

#### Dot notation para campos anidados
```python
# Actualizar solo la ciudad
doc_ref.update({
    "user.address.city": "Barcelona"
})

# Eliminar un campo específico del map
doc_ref.update({
    "user.address.street": firestore.DELETE_FIELD
})
```

#### Set con merge en maps
```python
# Actualiza solo name, mantiene age y address
doc_ref.set({
    "user": {
        "name": "Pedro"
    }
}, merge=True)
```

### Arrays dentro de Maps
Los arrays mantienen su comportamiento nativo dentro de maps:

```python
# Map con arrays internos
user_data = {
    "user": {
        "name": "Juan",
        "tags": ["developer", "python"],  # Sigue siendo array
        "preferences": {
            "languages": ["es", "en"]     # También array
        }
    }
}

# Operaciones en arrays anidados
doc_ref.update({
    "user.tags": firestore.ArrayUnion(["javascript"]),
    "user.preferences.languages": firestore.ArrayRemove(["en"])
})
```

## Limitaciones de Tamaño

### Límite de 1MB por documento
- **Incluye**: datos + nombres de atributos + metadatos
- **Nombres largos consumen bytes innecesariamente**
- **Arrays de objects replican nombres de campos**

```python
# Menos eficiente (nombres repetidos)
"orders": [
    {"product_name": "A", "quantity": 1},
    {"product_name": "B", "quantity": 2}
]

# Más eficiente  
"orders": [
    {"name": "A", "qty": 1},
    {"name": "B", "qty": 2}
]
```

## Trade-off: Map Grande vs Múltiples Documentos

### Map Grande (Desnormalizado)
**Pros:**
- 1 lectura para obtener toda la entidad
- Consistencia atómica
- Menos complejidad en queries

**Contras:**
- Escrituras costosas (reescribe todo el documento)
- Concurrencia limitada
- Transferencia innecesaria de datos

### Múltiples Documentos (Normalizado)
**Pros:**
- Escrituras eficientes
- Mejor concurrencia
- Transferencia optimizada

**Contras:**
- Múltiples lecturas = más operaciones facturadas
- Sin atomicidad entre documentos
- Queries más complejas

## Array de Maps vs Subcollections

### Para Eliminar Elementos

#### Array de Maps
```python
# Opción 1: ArrayRemove (necesitas el map exacto)
order_to_remove = {"id": "order2", "amount": 50, "status": "pending"}
doc_ref.update({
    "orders": firestore.ArrayRemove([order_to_remove])
})

# Opción 2: Set completo (lectura + escritura)
doc = doc_ref.get().to_dict()
orders = [order for order in orders if order["id"] != "order2"]
doc_ref.update({"orders": orders})
```

#### Subcollection
```python
# Eliminación directa por ID
doc_ref.collection("orders").document("order2").delete()
```

### Consideraciones
- **Array de maps**: 1 lectura para todos los elementos, atomicidad
- **Subcollection**: Eliminación directa sin leer primero, mejor para elementos independientes

## Recomendaciones Generales

1. **Usa maps** para value objects y datos que cambian juntos
2. **Evita duplicados** si planeas usar `ArrayUnion`
3. **Nombres de campos concisos** pero descriptivos
4. **Evalúa patrones de uso** antes de elegir entre normalizado vs desnormalizado
5. **Considera subcollections** para elementos que crecen indefinidamente o cambian independientemente