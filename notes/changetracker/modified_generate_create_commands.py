"""
Modificación del método _generate_create_commands en change_tracker.py

UBICACIÓN: Líneas 206-222 del archivo change_tracker.py

CAMBIOS:
1. Usar current_document en lugar de original_snapshot
2. Aplicar _filter_none_recursive antes de generar comandos
"""


def _generate_create_commands(
    self, tracked_entity: TrackedEntity
) -> List[AbstractCommand]:
    """
    Genera comandos CREATE recursivos para toda la estructura.
    
    MODIFICACIONES:
    - Usa current_document en lugar de original_snapshot para capturar el estado actual
    - Filtra valores None recursivamente antes de generar comandos
    - Garantiza que los comandos CREATE no contengan campos con valor None
    
    Args:
        tracked_entity: Entidad trackeada con estado ADDED
        
    Returns:
        Lista de AbstractCommand con operation=CREATE
        
    Comportamiento:
    - Genera comandos recursivos para toda la jerarquía (Store → Products → Category)
    - Excluye campos con valor None de los comandos
    - Preserva objetos especiales (DocumentId, CollectionReference, GeoPointValue)
    - Mantiene la estructura de collections
    """
    commands = []
    
    # ✅ CAMBIO 1: Usar current_document en vez de original_snapshot
    # Esto captura el estado actual del documento, incluyendo cambios posteriores
    # al tracking inicial
    current_snapshot = self._create_snapshot(tracked_entity.current_document)
    
    # ✅ CAMBIO 2: Filtrar None values recursivamente
    # _filter_none_recursive procesa:
    # - Dicts: Excluye keys con value None
    # - Lists: Filtra items None
    # - Objetos especiales: Los preserva sin modificar (DocumentId, etc.)
    filtered_snapshot = self._filter_none_recursive(current_snapshot)
    
    # Recorrer recursivamente toda la estructura y generar comandos CREATE
    # Este método no cambia, solo recibe data ya filtrada
    self._generate_recursive_commands(
        data=filtered_snapshot,
        level=0,
        commands=commands,
        operation=OperationType.CREATE,
        entity_type=tracked_entity.entity_type,
    )
    
    return commands


"""
EJEMPLO DE USO:

ANTES (con None values):
store = Store(
    name="TechStore",
    description=None,  # ❌ Aparecía en el comando CREATE
    location=(40.0, -3.0)
)

Comando generado ANTES:
{
    "operation": "CREATE",
    "entity_id": "stores/123",
    "data": {
        "name": "TechStore",
        "description": None,  # ❌ No debería estar
        "location": {"latitude": 40.0, "longitude": -3.0}
    }
}

DESPUÉS (sin None values):
Comando generado DESPUÉS:
{
    "operation": "CREATE",
    "entity_id": "stores/123",
    "data": {
        "name": "TechStore",
        "location": {"latitude": 40.0, "longitude": -3.0}
        # ✅ description no aparece porque era None
    }
}
"""


"""
VALIDACIÓN:

El método modificado garantiza:
1. ✅ Campos con None no aparecen en comandos CREATE
2. ✅ Campos con valores válidos sí aparecen
3. ✅ Collections anidadas también se filtran correctamente
4. ✅ Objetos especiales (DocumentId, GeoPointValue) se preservan
5. ✅ La estructura recursiva se mantiene intacta

Tests incluidos en test_change_tracker_add.py validan estos comportamientos.
"""
