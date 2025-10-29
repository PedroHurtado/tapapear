# Modificaciones para ChangeTracker - ADD Operation

## Análisis del Problema

El método `_generate_create_commands` actualmente tiene estos problemas:

1. **Usa `original_snapshot`**: Cuando se crea un documento nuevo (ADD), el snapshot se toma con los valores iniciales, pero no filtra los valores `None`
2. **No filtra `None` values**: Los comandos CREATE deben excluir campos con valor `None` para evitar escribir valores nulos innecesarios
3. **Falta de filtering en collections**: Los items dentro de collections también pueden tener campos `None` que deben filtrarse

## Solución Propuesta

### 1. Modificar `_generate_create_commands`

```python
def _generate_create_commands(
    self, tracked_entity: TrackedEntity
) -> List[AbstractCommand]:
    """Genera comandos CREATE recursivos para toda la estructura"""
    commands = []
    
    # Obtener snapshot actual del documento (no el original)
    current_snapshot = self._create_snapshot(tracked_entity.current_document)
    
    # Filtrar None values recursivamente antes de generar comandos
    filtered_snapshot = self._filter_none_recursive(current_snapshot)
    
    # Recorrer recursivamente toda la estructura y generar comandos CREATE
    self._generate_recursive_commands(
        data=filtered_snapshot,
        level=0,
        commands=commands,
        operation=OperationType.CREATE,
        entity_type=tracked_entity.entity_type,
    )
    
    return commands
```

**Cambios clave:**
- Usar `current_document` en lugar de `original_snapshot` para obtener el estado actual
- Aplicar `_filter_none_recursive` al snapshot antes de generar comandos
- Esto garantiza que ningún campo `None` llegue a los comandos CREATE

### 2. Verificar `_filter_none_recursive`

El método ya existe pero necesita asegurar que:
- Filtra `None` en dicts recursivamente
- Filtra items `None` en listas
- Preserva objetos especiales como `DocumentId`, `CollectionReference`, `GeoPointValue`

**El método actual está bien implementado**, solo necesitamos usarlo en CREATE.

### 3. No modificar `_generate_recursive_commands`

Este método ya maneja correctamente:
- La separación de collections vs command data
- La exclusión de campos especiales (`__class__`)
- El procesamiento recursivo de collections

Solo necesita recibir data ya filtrada.

## Resumen de Cambios

**Archivo: `change_tracker.py`**

**Línea 206-222**: Reemplazar método `_generate_create_commands`

```python
def _generate_create_commands(
    self, tracked_entity: TrackedEntity
) -> List[AbstractCommand]:
    """Genera comandos CREATE recursivos para toda la estructura"""
    commands = []
    
    # ✅ CAMBIO 1: Usar current_document en vez de original_snapshot
    current_snapshot = self._create_snapshot(tracked_entity.current_document)
    
    # ✅ CAMBIO 2: Filtrar None values recursivamente
    filtered_snapshot = self._filter_none_recursive(current_snapshot)
    
    # Recorrer recursivamente toda la estructura y generar comandos CREATE
    self._generate_recursive_commands(
        data=filtered_snapshot,
        level=0,
        commands=commands,
        operation=OperationType.CREATE,
        entity_type=tracked_entity.entity_type,
    )
    
    return commands
```

## ¿Por qué funciona?

1. **Current vs Original**: En ADD, el documento puede tener campos modificados después de ser creado pero antes de `save_changes()`. Usar `current_document` garantiza el estado más reciente.

2. **Filter None**: Los comandos CREATE no deben incluir campos `None` porque:
   - No aportan información
   - Pueden causar errores en algunas bases de datos
   - Aumentan el tamaño del comando innecesariamente

3. **Recursivo**: `_filter_none_recursive` ya procesa:
   - Dicts: Excluye keys con value `None`
   - Lists: Excluye items `None`
   - Objetos especiales: Los preserva sin modificar

## Validación

El test debe verificar:
1. ✅ Campos con valor `None` no aparecen en comandos CREATE
2. ✅ Campos con valores válidos sí aparecen
3. ✅ Collections anidadas también se filtran
4. ✅ Referencias y objetos especiales se preservan
5. ✅ El orden de comandos (level) es correcto
