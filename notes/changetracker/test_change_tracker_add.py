"""
Test para validar el filtrado de None values en operaciones CREATE del ChangeTracker
"""

from typing import List, Set, Optional, Union
from enum import Enum
from uuid import uuid4

from common.infrastructure import Document, reference, collection, geopoint
from common.infrastructure.agregate_root import agregate_root
from common.infrastructure.change_tracker import (
    ChangeTracker,
    ChangeType,
    OperationType,
    DatabaseDialect,
    AbstractCommand,
)


# ===== MOCK DATABASE DIALECT =====


class MockDialect(DatabaseDialect):
    """Mock dialect para capturar comandos sin ejecutarlos"""

    def __init__(self):
        super().__init__(db=None, transaction=None)
        self.executed_commands = []

    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Captura los comandos en lugar de ejecutarlos"""
        self.executed_commands.extend(commands)

    def sort_commands(
        self, commands: List[AbstractCommand], change_type: ChangeType
    ) -> List[AbstractCommand]:
        """Ordena por level (mayor a menor para CREATE)"""
        if change_type == ChangeType.ADDED:
            return sorted(commands, key=lambda c: c.level, reverse=True)
        return commands


# ===== MODELO DE DATOS =====


class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Category(Document):
    name: str
    description: Optional[str] = None  # Campo opcional


class Tag(Document):
    name: str
    color: Optional[str] = None  # Campo opcional


class Product(Document):
    name: str
    price: float
    category: Optional[Category] = reference()  # Reference opcional
    tags: Set[Tag] = set()
    description: Optional[str] = None  # Campo opcional
    coordinates: Optional[Union[tuple, dict]] = geopoint()  # Geopoint opcional
    status: Status


@agregate_root
class Store(Document):
    name: str
    location: Union[tuple, dict] = geopoint()
    products: List[Product] = collection()
    categories: List[Category] = collection()
    region: str
    description: Optional[str] = None  # Campo opcional
    phone_numbers: List[str] = []


# ===== TESTS =====


def test_create_with_none_values():
    """
    Test 1: Verificar que campos None no aparecen en comandos CREATE
    """
    print("\n🧪 TEST 1: CREATE con campos None")
    print("=" * 60)

    # Crear datos con campos None
    electronics = Category(
        name="Electronics",
        description=None,  # ❌ None - NO debe aparecer en comando
    )

    tag_premium = Tag(
        name="Premium",
        color=None,  # ❌ None - NO debe aparecer en comando
    )

    laptop = Product(
        name="Gaming Laptop",
        price=1299.99,
        category=electronics,
        tags={tag_premium},
        description=None,  # ❌ None - NO debe aparecer en comando
        coordinates=None,  # ❌ None - NO debe aparecer en comando
        status=Status.ACTIVE,
    )

    store = Store(
        name="TechStore",
        location=(40.4168, -3.7038),
        products=[laptop],
        categories=[electronics],
        region="Madrid",
        description=None,  # ❌ None - NO debe aparecer en comando
    )

    # Setup tracker
    dialect = MockDialect()
    tracker = ChangeTracker(dialect=dialect)

    # Track como ADDED
    tracker.set_entity(store, ChangeType.ADDED)

    # Guardar cambios
    tracker.save_changes()

    # Validar comandos generados
    commands = dialect.executed_commands

    print(f"\n📦 Comandos generados: {len(commands)}")

    # Verificar que hay 4 comandos (Store, Product, Category, Tag)
    assert len(commands) == 4, f"Expected 4 commands, got {len(commands)}"

    # Analizar cada comando
    for cmd in commands:
        print(f"\n🔍 Comando: {cmd.operation.value} - Level {cmd.level}")
        print(f"   Entity ID: {cmd.entity_id.path}")
        print(f"   Data keys: {list(cmd.data.keys())}")

        # ✅ REGLA: Ningún campo en data debe tener valor None
        for key, value in cmd.data.items():
            assert (
                value is not None
            ), f"Campo '{key}' tiene valor None en comando {cmd.entity_id.path}"
            print(f"   ✓ {key}: {type(value).__name__}")

        # ✅ REGLA: Los campos opcionales con None NO deben aparecer
        if "Store" in cmd.entity_id.path:
            assert "description" not in cmd.data, "Store.description (None) no debe aparecer"
            assert "name" in cmd.data, "Store.name debe aparecer"
            assert "location" in cmd.data, "Store.location debe aparecer"

        elif "Product" in cmd.entity_id.path:
            assert "description" not in cmd.data, "Product.description (None) no debe aparecer"
            assert "coordinates" not in cmd.data, "Product.coordinates (None) no debe aparecer"
            assert "name" in cmd.data, "Product.name debe aparecer"
            assert "price" in cmd.data, "Product.price debe aparecer"

        elif "Category" in cmd.entity_id.path:
            assert "description" not in cmd.data, "Category.description (None) no debe aparecer"
            assert "name" in cmd.data, "Category.name debe aparecer"

        elif "Tag" in cmd.entity_id.path:
            assert "color" not in cmd.data, "Tag.color (None) no debe aparecer"
            assert "name" in cmd.data, "Tag.name debe aparecer"

    print("\n✅ TEST 1 PASSED: Campos None correctamente filtrados")


def test_create_with_all_values():
    """
    Test 2: Verificar que campos con valores válidos SÍ aparecen en comandos CREATE
    """
    print("\n🧪 TEST 2: CREATE con todos los valores")
    print("=" * 60)

    # Crear datos SIN campos None
    books = Category(
        name="Books",
        description="Reading materials",  # ✅ Tiene valor
    )

    tag_sale = Tag(
        name="Sale",
        color="red",  # ✅ Tiene valor
    )

    book = Product(
        name="Python Guide",
        price=45.00,
        category=books,
        tags={tag_sale},
        description="Advanced Python programming",  # ✅ Tiene valor
        coordinates={"latitude": 41.3851, "longitude": 2.1734},  # ✅ Tiene valor
        status=Status.INACTIVE,
    )

    store = Store(
        name="BookStore",
        location=(40.4168, -3.7038),
        products=[book],
        categories=[books],
        region="Barcelona",
        description="Best bookstore in town",  # ✅ Tiene valor
    )

    # Setup tracker
    dialect = MockDialect()
    tracker = ChangeTracker(dialect=dialect)

    # Track como ADDED
    tracker.set_entity(store, ChangeType.ADDED)

    # Guardar cambios
    tracker.save_changes()

    # Validar comandos generados
    commands = dialect.executed_commands

    print(f"\n📦 Comandos generados: {len(commands)}")

    # Analizar cada comando
    for cmd in commands:
        print(f"\n🔍 Comando: {cmd.operation.value} - Level {cmd.level}")
        print(f"   Entity ID: {cmd.entity_id.path}")
        print(f"   Data keys: {list(cmd.data.keys())}")

        # ✅ REGLA: Todos los campos con valores deben aparecer
        if "Store" in cmd.entity_id.path:
            assert "description" in cmd.data, "Store.description debe aparecer"
            assert cmd.data["description"] == "Best bookstore in town"

        elif "Product" in cmd.entity_id.path:
            assert "description" in cmd.data, "Product.description debe aparecer"
            assert "coordinates" in cmd.data, "Product.coordinates debe aparecer"
            assert cmd.data["description"] == "Advanced Python programming"

        elif "Category" in cmd.entity_id.path:
            assert "description" in cmd.data, "Category.description debe aparecer"
            assert cmd.data["description"] == "Reading materials"

        elif "Tag" in cmd.entity_id.path:
            assert "color" in cmd.data, "Tag.color debe aparecer"
            assert cmd.data["color"] == "red"

    print("\n✅ TEST 2 PASSED: Todos los valores válidos aparecen correctamente")


def test_create_mixed_values():
    """
    Test 3: Verificar combinación de campos con valores y None
    """
    print("\n🧪 TEST 3: CREATE con valores mixtos")
    print("=" * 60)

    # Mix: algunos None, algunos con valores
    cat1 = Category(name="Cat1", description="Has description")
    cat2 = Category(name="Cat2", description=None)

    tag1 = Tag(name="Tag1", color="blue")
    tag2 = Tag(name="Tag2", color=None)

    product = Product(
        name="Mixed Product",
        price=99.99,
        category=cat1,
        tags={tag1, tag2},
        description=None,  # None
        coordinates=(40.0, -3.0),  # Has value
        status=Status.ACTIVE,
    )

    store = Store(
        name="Mixed Store",
        location=(40.0, -3.0),
        products=[product],
        categories=[cat1, cat2],
        region="Madrid",
        description="Has description",
    )

    # Setup tracker
    dialect = MockDialect()
    tracker = ChangeTracker(dialect=dialect)
    tracker.set_entity(store, ChangeType.ADDED)
    tracker.save_changes()

    commands = dialect.executed_commands
    print(f"\n📦 Comandos generados: {len(commands)}")

    # Validar cada comando
    for cmd in commands:
        entity_path = cmd.entity_id.path
        print(f"\n🔍 {entity_path}")

        if "Cat1" in entity_path or "categories" in entity_path:
            # Cat1 tiene description
            if cmd.data.get("name") == "Cat1":
                assert "description" in cmd.data
                assert cmd.data["description"] == "Has description"
                print("   ✓ Cat1: description presente")

        if "Cat2" in entity_path:
            # Cat2 NO tiene description
            if cmd.data.get("name") == "Cat2":
                assert "description" not in cmd.data
                print("   ✓ Cat2: description ausente (None)")

        if "Tag1" in entity_path or "tags" in entity_path:
            if cmd.data.get("name") == "Tag1":
                assert "color" in cmd.data
                assert cmd.data["color"] == "blue"
                print("   ✓ Tag1: color presente")

        if "Tag2" in entity_path:
            if cmd.data.get("name") == "Tag2":
                assert "color" not in cmd.data
                print("   ✓ Tag2: color ausente (None)")

        if "Product" in entity_path:
            assert "description" not in cmd.data  # None
            assert "coordinates" in cmd.data  # Has value
            print("   ✓ Product: description ausente, coordinates presente")

    print("\n✅ TEST 3 PASSED: Valores mixtos manejados correctamente")


def test_command_order():
    """
    Test 4: Verificar orden correcto de comandos (level)
    """
    print("\n🧪 TEST 4: Orden de comandos CREATE")
    print("=" * 60)

    electronics = Category(name="Electronics", description="Devices")
    laptop = Product(
        name="Laptop",
        price=999.99,
        category=electronics,
        status=Status.ACTIVE,
    )

    store = Store(
        name="Store",
        location=(40.0, -3.0),
        products=[laptop],
        categories=[electronics],
        region="Madrid",
    )

    dialect = MockDialect()
    tracker = ChangeTracker(dialect=dialect)
    tracker.set_entity(store, ChangeType.ADDED)
    tracker.save_changes()

    commands = dialect.executed_commands

    # Los comandos deben estar ordenados por level descendente
    # Level más alto (nested) primero
    levels = [cmd.level for cmd in commands]
    print(f"\n📊 Levels: {levels}")

    # Verificar que está ordenado descendente
    assert levels == sorted(
        levels, reverse=True
    ), "Comandos deben estar ordenados por level (DESC)"

    # Level 0 debe ser Store
    assert "stores" in commands[-1].entity_id.path, "Último comando debe ser Store (level 0)"

    print("\n✅ TEST 4 PASSED: Orden de comandos correcto")


# ===== RUNNER =====


def run_all_tests():
    """Ejecuta todos los tests"""
    print("\n" + "=" * 60)
    print("🚀 INICIANDO TESTS DE CHANGE TRACKER - ADD OPERATION")
    print("=" * 60)

    try:
        test_create_with_none_values()
        test_create_with_all_values()
        test_create_mixed_values()
        test_command_order()

        print("\n" + "=" * 60)
        print("✅ TODOS LOS TESTS PASARON EXITOSAMENTE")
        print("=" * 60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()
