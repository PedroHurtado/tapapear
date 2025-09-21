from typing import List, Set, Union, Tuple
from enum import Enum
import json
from uuid import uuid4

# Importaciones del proyecto
from common.infrastructure import Document, reference, collection, geopoint
from common.infrastructure.change_tracker import (
    ChangeTracker, 
    DatabaseDialect, 
    ChangeType, 
    AbstractCommand,
    OperationType,
    ArrayOperation
)

# ==================== MODELOS STORE ====================

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class Category(Document):
    name: str
    description: str

class Tag(Document):
    name: str
    color: str

class Product(Document):
    name: str
    price: float
    category: Category = reference()
    tags: Set[Tag] = set()  # Set normal, no collection
    coordinates: Union[tuple, dict] = geopoint()  # Acepta tuple o dict
    status: Status

class Foo(Product):
    pass

class Store(Document):
    name: str
    location: Union[tuple, dict] = geopoint()
    products: List[Product] = collection()
    categories: List[Category] = collection("categories/{name}")
    region: str
    phone_numbers: List[str] = []  # Lista simple
    operating_hours: Tuple[int, int] = (9, 18)  # Tuple simple

# ==================== DIALECT JSON FICTICIO ====================

class JSONDialect(DatabaseDialect):
    """Dialect ficticio que convierte comandos a JSON para testing"""
    
    def __init__(self):
        self.executed_commands = []
    
    def execute_commands(self, commands: List[AbstractCommand]) -> None:
        """Convierte comandos a JSON y los almacena"""
        for command in commands:
            json_command = command.model_dump(mode="json")
            self.executed_commands.append(json_command)
            print(f"📋 JSON Command: {json.dumps(json_command, indent=2)}")
    
    def sort_commands(self, commands: List[AbstractCommand], change_type: ChangeType) -> List[AbstractCommand]:
        """Ordenamiento simple por level (profundos primero para DELETE, shallow primero para CREATE)"""
        if change_type == ChangeType.DELETED:
            return sorted(commands, key=lambda cmd: cmd.level, reverse=True)
        else:
            return sorted(commands, key=lambda cmd: cmd.level)
    
    def get_executed_commands_json(self) -> str:
        """Retorna todos los comandos ejecutados en formato JSON"""
        return json.dumps(self.executed_commands, indent=2)
    
    def clear_commands(self):
        """Limpia el historial de comandos"""
        self.executed_commands = []

# ==================== BATERÍA DE DATOS - SOLO ADDED ====================

def create_test_store_simple() -> Store:
    """Crea un Store simple sin colecciones anidadas"""
    
    store = Store(
        name="Tech Store Downtown",
        location={"latitude": 40.7128, "longitude": -74.0060},  # Nueva York
        products=[],  # Lista vacía
        categories=[],  # Lista vacía
        region="North America",
        phone_numbers=["555-0123", "555-0124"],
        operating_hours=(9, 21)
    )
    
    return store

def create_test_store_with_categories() -> Store:
    """Crea un Store con categorías (collection con patrón)"""
    
    electronics = Category(
        name="Electronics",
        description="Electronic devices and gadgets"
    )
    
    books = Category(
        name="Books", 
        description="Physical and digital books"
    )
    
    store = Store(
        name="Mega Store",
        location={"latitude": 51.5074, "longitude": -0.1278},  # Londres
        products=[],
        categories=[electronics, books],
        region="Europe",
        phone_numbers=["44-20-1234"],
        operating_hours=(8, 20)
    )
    
    return store

def create_test_store_with_products() -> Store:
    """Crea un Store con productos (collection normal + referencias)"""
    
    # Crear categoría
    tech_category = Category(
        name="Technology",
        description="Tech products"
    )
    
    # Crear tags
    popular_tag = Tag(name="Popular", color="red")
    new_tag = Tag(name="New", color="green")
    
    # Crear productos
    laptop = Product(
        name="Gaming Laptop",
        price=1299.99,
        category=tech_category,
        tags={popular_tag, new_tag},
        coordinates={"latitude": 37.7749, "longitude": -122.4194},  # San Francisco
        status=Status.ACTIVE
    )
    
    mouse = Product(
        name="Wireless Mouse",
        price=29.99,
        category=tech_category,
        tags={popular_tag},
        coordinates={"latitude": 37.7749, "longitude": -122.4194},
        status=Status.ACTIVE
    )
    
    store = Store(
        name="Tech Hub",
        location={"latitude": 37.7749, "longitude": -122.4194},
        products=[laptop, mouse],
        categories=[tech_category],
        region="North America",
        phone_numbers=["415-555-0001"],
        operating_hours=(10, 22)
    )
    
    return store

def create_test_store_complex() -> Store:
    """Crea un Store complejo con todos los tipos de datos"""
    
    # Categorías
    electronics = Category(name="Electronics", description="Electronic devices")
    books = Category(name="Books", description="Literature and education")
    clothing = Category(name="Clothing", description="Fashion and apparel")
    
    # Tags
    bestseller = Tag(name="Bestseller", color="gold")
    eco_friendly = Tag(name="Eco-Friendly", color="green")
    premium = Tag(name="Premium", color="purple")
    sale = Tag(name="Sale", color="red")
    
    # Productos complejos
    smartphone = Product(
        name="Smartphone Pro Max",
        price=999.99,
        category=electronics,
        tags={bestseller, premium},
        coordinates={"latitude": 40.7589, "longitude": -73.9851},  # Times Square
        status=Status.ACTIVE
    )
    
    novel = Product(
        name="Science Fiction Novel",
        price=15.99,
        category=books,
        tags={bestseller, eco_friendly},
        coordinates={"latitude": 40.7589, "longitude": -73.9851},
        status=Status.ACTIVE
    )
    
    tshirt = Product(
        name="Organic Cotton T-Shirt",
        price=25.50,
        category=clothing,
        tags={eco_friendly, sale},
        coordinates={"latitude": 40.7589, "longitude": -73.9851},
        status=Status.INACTIVE  # Producto inactivo
    )
    
    # Store complejo
    store = Store(
        name="Universal Megastore",
        location={"latitude": 40.7589, "longitude": -73.9851},
        products=[smartphone, novel, tshirt],
        categories=[electronics, books, clothing],
        region="North America",
        phone_numbers=["212-555-0001", "212-555-0002", "1-800-MEGA-STORE"],
        operating_hours=(6, 24)  # 24/7 casi
    )
    
    return store

# ==================== FUNCIONES DE TESTING ====================

def test_store_added(store: Store, test_name: str):
    """Testa un Store con estado ADDED"""
    
    print(f"\n{'='*60}")
    print(f"🧪 TESTING: {test_name}")
    print(f"{'='*60}")
    
    # Crear dialect JSON
    dialect = JSONDialect()
    tracker = ChangeTracker(dialect)
    
    # Trackear el store como ADDED
    tracker.set_entity(store, ChangeType.ADDED)
    
    print(f"📊 Store: {store.name}")
    print(f"📊 Products: {len(store.products)}")
    print(f"📊 Categories: {len(store.categories)}")
    
    # Guardar cambios (genera comandos)
    print(f"\n🚀 Generating commands...")
    tracker.save_changes()
    
    # Mostrar resumen
    print(f"\n📋 Total commands generated: {len(dialect.executed_commands)}")
    
    # Guardar en archivo para inspección
    filename = f"test_{test_name.lower().replace(' ', '_')}.json"
    with open(filename, 'w') as f:
        f.write(dialect.get_executed_commands_json())
    
    print(f"💾 Commands saved to: {filename}")
    
    return dialect.executed_commands

def run_all_tests():
    """Ejecuta todos los tests de la batería"""
    
    print("🎯 STARTING STORE BATTERY TESTS - ADDED ONLY")
    
    # Test 1: Store simple
    store1 = create_test_store_simple()
    test_store_added(store1, "Simple Store")
    
    # Test 2: Store con categorías
    store2 = create_test_store_with_categories()
    test_store_added(store2, "Store with Categories")
    
    # Test 3: Store con productos
    store3 = create_test_store_with_products()
    test_store_added(store3, "Store with Products")
    
    # Test 4: Store complejo
    store4 = create_test_store_complex()
    test_store_added(store4, "Complex Store")
    
    print(f"\n{'='*60}")
    print("✅ ALL TESTS COMPLETED")
    print(f"{'='*60}")

if __name__ == "__main__":
    run_all_tests()