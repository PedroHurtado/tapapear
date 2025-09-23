# Esquema Document - Documentación Completa

## 🎯 Objetivo

Generar un esquema flat optimizado desde modelos Pydantic para simplificar la serialización y tracking de cambios, eliminando la complejidad de introspección en runtime.

## 🏗️ Estructura General

```json
{
  "EntityName": {
    "properties": {
      "field_name": {
        "type": "field_type",
        "strategy": "serialization_strategy",
        "metadata": { /* opcional */ }
      }
    },
    "entity_metadata": {
      "type": "document|embeddable",
      "entity_name": "EntityName",
      "id_field": "id",
      "collection_name": "entities",
      "dependencies": {
        "documents": ["RelatedEntity"],
        "embeddables": ["EmbeddedEntity"]
      }
    }
  }
}
```

## 📊 Tipos de Campos (properties)

### 1. ID Fields
```json
"id": {
  "type": "id",
  "strategy": "id_field"
}
```

**Origen:** `id: UUID = id()`  
**Uso:** Identifica documentos, genera DocumentId/CollectionReference según contexto

---

### 2. Primitive Fields
```json
"name": {
  "type": "primitive",
  "strategy": "direct"
},
"price": {
  "type": "primitive", 
  "strategy": "direct"
}
```

**Origen:** `name: str`, `price: float`, `active: bool`  
**Uso:** Serialización directa sin transformación

---

### 3. Enum Fields
```json
"status": {
  "type": "enum",
  "strategy": "direct"
}
```

**Origen:** `status: Status` (donde Status es Enum)  
**Uso:** Serialización directa del valor enum

---

### 4. Geopoint Fields
```json
"location": {
  "type": "geopoint",
  "strategy": "geopoint_value"
}
```

**Origen:** `location: Union[tuple, dict] = geopoint()`  
**Uso:** Convierte tuple/dict a GeoPointValue

---

### 5. Reference Fields
```json
"category": {
  "type": "reference",
  "strategy": "reference_path",
  "reference_metadata": {
    "target_entity": "Category",
    "path_resolver": "categories/{Category.id}"
  }
}
```

**Origen:** `category: Category = reference()`  
**Variantes de path_resolver:**
- **Sin patrón:** `reference()` → `"categories/{Category.id}"`
- **Patrón fijo:** `reference("users")` → `"users/{Category.id}"`
- **Patrón con placeholder:** `reference("users/{name}")` → `"users/{Category.name}"`

---

### 6. Collection Fields
```json
"products": {
  "type": "collection",
  "strategy": "collection_with_paths",
  "collection_metadata": {
    "element_entity": "Product",
    "path_pattern": "stores/{Store.id}/products/{Product.id}",
    "reference_field": "id",
    "diff_strategy": "by_id"
  }
}
```

**Origen:** `products: List[Product] = collection()`  
**Variantes de path_pattern:**
- **Sin patrón:** `collection()` → `"stores/{Store.id}/products/{Product.id}"`
- **Patrón con placeholder:** `collection("categories/{name}")` → `"stores/{Store.id}/categories/{Category.name}"`

---

### 7. Simple Array Fields
```json
"phone_numbers": {
  "type": "simple_array",
  "strategy": "direct_array",
  "array_metadata": {
    "element_type": "str",
    "diff_strategy": "array_operations"
  }
}
```

**Origen:** `phone_numbers: List[str]`  
**Elementos:** Tipos primitivos (str, int, float, bool)

---

### 8. Set Fields
```json
"tags": {
  "type": "set",
  "strategy": "set_to_list", 
  "array_metadata": {
    "element_type": "Tag",
    "diff_strategy": "set_comparison"
  }
}
```

**Origen:** `tags: Set[Tag]`  
**Serialización:** Convierte a lista con ordenamiento inteligente:
- **Primitivos:** Ordenados (`Set[str]` → `["a", "b", "c"]`)
- **Objetos con ID:** Ordenados por ID (`Set[Tag]` → ordenado por `tag.id`)
- **Otros:** Lista sin orden específico

**Implementación en MixinSerializer:**
```python
def _serialize_set_field(self, value: Set) -> List:
    items = list(value)
    if not items:
        return []
    
    # Primitivos - ordenar directamente
    if isinstance(items[0], (str, int, float)):
        return sorted(items)
    
    # Objetos con ID - ordenar por ID
    elif hasattr(items[0], 'id'):
        return sorted(items, key=lambda x: str(x.id))
    
    # Sin ordenamiento específico
    return items
```

---

### 9. Tuple Fields
```json
"operating_hours": {
  "type": "tuple",
  "strategy": "tuple_to_list",
  "array_metadata": {
    "element_type": "mixed",
    "diff_strategy": "direct_comparison"
  }
}
```

**Origen:** `operating_hours: Tuple[int, int]`  
**Serialización:** Convierte a lista para compatibilidad JSON

**Implementación en MixinSerializer:**
```python
def _serialize_tuple_field(self, value: Tuple) -> List:
    return list(value)
```

---

### 10. Object Array Fields
```json
"items": {
  "type": "object_array",
  "strategy": "direct_array",
  "array_metadata": {
    "element_type": "Item",
    "diff_strategy": "by_id"
  }
}
```

**Origen:** `items: List[Item]` (donde Item NO tiene metadata collection)  
**Uso:** Arrays de objetos sin path tracking

---

### 11. Embedded Fields
```json
"contact_info": {
  "type": "embedded",
  "strategy": "direct"
}
```

**Origen:** `contact_info: ContactInfo` (objeto directo)  
**Uso:** Value objects anidados

## 🏷️ Entity Metadata

### Document Entity
```json
"entity_metadata": {
  "type": "document",
  "entity_name": "Store",
  "id_field": "id",
  "collection_name": "stores",
  "dependencies": {
    "documents": ["Category", "Product", "Tag"],
    "embeddables": ["ContactInfo"]
  }
}
```

**Características:**
- `type: "document"` - Entidad independiente con ID
- `id_field` - Campo que actúa como identificador
- `collection_name` - Nombre de la colección (pluralizado)
- `dependencies` - Para ordering de comandos y debug

### Embeddable Entity
```json
"entity_metadata": {
  "type": "embeddable",
  "entity_name": "Address",
  "id_field": "id",
  "dependencies": {
    "documents": ["Country"],
    "embeddables": []
  }
}
```

**Características:**
- `type: "embeddable"` - Value object que puede estar en subcollections
- `id_field` opcional - Si tiene ID, puede estar en subcollections
- Sin `collection_name` - No es entidad root

### Value Object Simple
```json
"entity_metadata": {
  "type": "embeddable",
  "entity_name": "ContactInfo"
}
```

**Características:**
- Sin `id_field` - No puede estar en subcollections
- Sin `dependencies` - Solo campos primitivos

## 🔗 Path Resolution con Dot Notation

### Cómo Resolvemos Paths

**Conversión automática de placeholders simples a dot notation:**

```python
def _resolve_path_pattern(self, pattern: str, target_entity: str) -> str:
    """Convierte {field} a {EntityName.field}"""
    resolved = pattern
    
    placeholders = re.findall(r'\{([^}]+)\}', pattern)
    for placeholder in placeholders:
        if placeholder == 'id':
            # {id} se refiere al target entity
            resolved = resolved.replace('{id}', f'{{{target_entity}.id}}')
        elif placeholder == 'name':
            # {name} se refiere al target entity  
            resolved = resolved.replace('{name}', f'{{{target_entity}.name}}')
        elif '.' not in placeholder:
            # Otros placeholders se asumen del target entity
            resolved = resolved.replace(f'{{{placeholder}}}', f'{{{target_entity}.{placeholder}}}')
    
    return resolved
```

### Patrones Automáticos

**Collection sin patrón:**
```python
products: List[Product] = collection()
```
```json
"path_pattern": "stores/{Store.id}/products/{Product.id}"
```

**Collection con patrón:**
```python
categories: List[Category] = collection("categories/{name}")
```
```json
"path_pattern": "stores/{Store.id}/categories/{Category.name}"
```

**Reference sin patrón:**
```python
category: Category = reference()
```
```json
"path_resolver": "categories/{Category.id}"
```

## 📈 Diff Strategies

### Arrays y Collections
- **`"array_operations"`** - Para List[primitives] (union/remove operations)
- **`"set_comparison"`** - Para Set[T] (comparación de conjuntos)
- **`"by_id"`** - Para List[Document] (tracking por ID)
- **`"direct_comparison"`** - Para Tuples (comparación directa)

### Uso en ChangeTracker
```python
field_schema = schema["Product"]["properties"]["tags"]
diff_strategy = field_schema["array_metadata"]["diff_strategy"]

if diff_strategy == "set_comparison":
    return detect_set_changes(old_value, new_value)
elif diff_strategy == "by_id":
    return detect_document_changes(old_value, new_value)
```

## 🚀 Casos de Uso Completos

### Store Completo
```json
{
  "Store": {
    "properties": {
      "id": {"type": "id", "strategy": "id_field"},
      "name": {"type": "primitive", "strategy": "direct"},
      "location": {"type": "geopoint", "strategy": "geopoint_value"},
      "products": {
        "type": "collection",
        "strategy": "collection_with_paths",
        "collection_metadata": {
          "element_entity": "Product",
          "path_pattern": "stores/{Store.id}/products/{Product.id}",
          "reference_field": "id",
          "diff_strategy": "by_id"
        }
      },
      "categories": {
        "type": "collection", 
        "strategy": "collection_with_paths",
        "collection_metadata": {
          "element_entity": "Category",
          "path_pattern": "stores/{Store.id}/categories/{Category.name}",
          "reference_field": "name",
          "diff_strategy": "by_id"
        }
      },
      "phone_numbers": {
        "type": "simple_array",
        "strategy": "direct_array",
        "array_metadata": {
          "element_type": "str",
          "diff_strategy": "array_operations"
        }
      }
    },
    "entity_metadata": {
      "type": "document",
      "entity_name": "Store",
      "id_field": "id",
      "collection_name": "stores",
      "dependencies": {
        "documents": ["Category", "Product"],
        "embeddables": []
      }
    }
  }
}
```

## 💡 Beneficios del Esquema

### Performance
- **O(1) field lookup** vs O(n) cache traversal
- **Pre-calculated paths** vs runtime resolution
- **Type-aware diff** vs blind comparison

### Simplicidad
- **Single source of truth** - Schema de Pydantic
- **Eliminación de ~350 líneas** de código complejo
- **Direct strategy mapping** - Sin if/elif chains

### Debug/Monitoring
- **Visibility inmediata** de dependencies
- **Clear path patterns** - No ambigüedad
- **Type information** preservada para troubleshooting

## 🎯 Uso con Decorador @entity

### @entity Decorator
```python
@entity  # Aplica SOLO a entidades root (Document classes principales)
class Store(Document):
    name: str
    products: List[Product] = collection()
    # Decorator genera automáticamente: Store.__document_schema__
```

**Importante:** 
- ✅ **Usar en:** Document classes principales (Store, User, Order, etc.)
- ❌ **NO usar en:** Embeddables, Value Objects o entidades hijas
- **Genera:** `__document_schema__` con esquema flat optimizado usando `generate_flat_schema()`

### Carga del Schema en Entidades Root
```python
@entity  # Decorator carga schema usando generate_flat_schema()
class Store(Document):
    # Decorator añade: Store.__document_schema__ = schema optimizado
    name: str
    products: List[Product] = collection()
    
# Acceso directo al schema
schema = Store.__document_schema__
```

### Serialización con Schema Lookup
```python
@field_serializer("*")
def serialize_field(self, value, info):
    # Acceso directo al schema pre-cargado
    schema = self.__class__.__document_schema__
    strategy = schema["properties"][info.field_name]["strategy"]
    return STRATEGY_MAP[strategy](value, info)

# Strategy implementations en MixinSerializer
STRATEGY_MAP = {
    "direct": lambda v, info: v,
    "id_field": self._serialize_id_field,
    "geopoint_value": self._serialize_geopoint_field,
    "reference_path": self._serialize_reference_field,
    "collection_with_paths": self._serialize_collection_field,
    "direct_array": lambda v, info: list(v) if v else [],
    "set_to_list": self._serialize_set_field,
    "tuple_to_list": self._serialize_tuple_field,
}
```

### Change Tracking con Schema Lookup
```python
def get_diff_strategy(self, entity_type, field_name):
    # Schema pre-cargado en el decorator
    schema = entity_type.__document_schema__
    return schema[entity_type.__name__]["properties"][field_name]["diff_strategy"]
```