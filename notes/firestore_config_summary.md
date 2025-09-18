# 📋 **Resumen Final: Configuración Pydantic para Firestore**

## **🔧 Funciones Field()**

### **Existentes (tuyas):**
- `id()` - ID de la entidad
- `reference()` - Referencia de Firestore (genera DocumentReference)
- `collection()` - Subcollection (genera CollectionReference, maneja cascade automático)

### **Nuevas (optimizaciones Firestore):**

```python
def array_union() -> Field:
    return Field(
        json_schema_extra={
            "array_operation": "union"
        }
    )

def array_remove() -> Field:
    return Field(
        json_schema_extra={
            "array_operation": "remove"
        }
    )

def enum_field() -> Field:
    """Convierte Enum del dominio a StringValue"""
    # Tu lógica de conversión Domain Enum → StringValue

def geopoint_field() -> Field:
    """Convierte Location VO del dominio a GeoPointValue"""  
    # Tu lógica de conversión Domain Location → GeoPointValue
```

## **⚙️ Config de entidad**

```python
class Config:
    auditable: bool = False                        # Log de cambios para auditoría
    timestamp_fields: List[TimestampField] = []    # Campos con SERVER_TIMESTAMP automático
    firestore_merge_default: bool = False          # Usar merge por defecto
```

## **🎯 Ejemplo de uso**

```python
class Order(Document):
    total: float
    status: str
    items: List[Item] = collection()
    tags: List[str] = array_union()
    
    class Config:
        auditable = True
        timestamp_fields = [TimestampField.UPDATED_AT]
        firestore_merge_default = True
```

## **✅ Principios respetados**

- **Pydantic = DTO** - Solo configuración técnica de persistencia
- **Dominio limpio** - Sin lógica de negocio en DTOs
- **Minimal config** - Solo lo esencial para Firestore
- **Type safety** - Enum para timestamp fields
- **No redundancia** - Sin configuración duplicada

**Total: 7 funciones Field() + 3 opciones Config**

## **🏗️ Arquitectura**

```
DOMINIO (limpio)
    ↓ (automapper)
PYDANTIC DTO (con config técnico mínimo)
    ↓ (detect_changes)
ABSTRACT COMMANDS (con metadata inferido)
    ↓ (firestore dialect)
FIRESTORE (persistencia optimizada)
```

## **🚫 Descartados (y por qué)**

- `affects_parent()` - El dominio ya maneja los recálculos
- `computed_field()` - Los valores vienen calculados del dominio
- `unique_field()` - Firestore no soporta índices únicos
- `transactional()` - Lo decide el mediator pipeline
- `triggers_recount()` - No hay lógica después, solo persistir
- `merge_field()` - Se maneja automáticamente por path
- `timestamped()` - Mejor a nivel de entidad
- `cascade_delete` - Ya lo maneja `collection()` automáticamente
- `prefer_batch_writes` - Con deletes siempre va a transaction
- `composite_indexes` - Se crean desde CLI, no SDK

## **🏗️ Clases generadas automáticamente**

### **StringValue (para enum_field):**
```python
class StringValue(BaseModel):
    value: str
    model_config = ConfigDict(frozen=True)

    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo):
        data = serializer(self)
        if info.mode == 'json':
            return data["value"]  # Solo el string al serializar
        else:
            return StringValue(**data)
```

### **GeoPointValue (para geopoint_field):**
```python
class GeoPointValue(BaseModel):
    latitude: float
    longitude: float
    model_config = ConfigDict(frozen=True)

    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info: SerializationInfo):
        data = serializer(self)
        if info.mode == 'json':
            return data  # Dict con lat/lng al serializar
        else:
            return GeoPointValue(**data)
```

## **🔄 Al dialect llegan instancias:**
```python
# Dict con instancias de clases
{
    "status": StringValue(value="pending"),
    "location": GeoPointValue(latitude=40.4168, longitude=-3.7038),
    "user_ref": DocumentReference(path="users/123")
}
```