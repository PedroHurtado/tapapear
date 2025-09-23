# Test simple para Document.py
# from document import Document, collection, reference, geopoint

from typing import List, Set, Tuple, Union
from enum import Enum
from uuid import uuid4

from common.infrastructure import Document,reference,collection,geopoint
from common.infrastructure.entity_decorator import entity
# ===== MODELO DE DATOS =====

class Status(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

@entity
class Category(Document):
    name: str
    description: str
@entity
class Tag(Document):
    name: str
    color: str
@entity
class Product(Document):
    name: str
    price: float
    category: Category = reference()
    tags: Set[Tag] = set()  # Set normal, no collection
    coordinates: Union[tuple, dict] = geopoint()  # Acepta tuple o dict
    status: Status

@entity
class Store(Document):
    name: str
    location: dict = geopoint()
    products: List[Product] = collection()
    categories: List[Category] = collection("categories/{name}")
    region: str
    phone_numbers: List[str] = []  # Lista simple
    operating_hours: Tuple[int, int] = (9, 18)  # Tuple simple

# ===== CARGA DE DATOS =====

def create_test_data():
    # Categorías
    electronics = Category(name="Electronics", description="Electronic devices")
    books = Category(name="Books", description="Reading materials")
    
    # Tags
    premium = Tag(name="Premium", color="gold")
    sale = Tag(name="Sale", color="red")
    new = Tag(name="New", color="blue")
    
    # Productos
    laptop = Product(
        name="Gaming Laptop",
        price=1299.99,
        category=electronics,
        tags={premium, new},  # Set
        coordinates=(40.4168, -3.7038),  # Tuple geopoint
        status=Status.ACTIVE
    )
    
    mouse = Product(
        name="Wireless Mouse", 
        price=25.50,
        category=electronics,
        tags={sale},  # Set
        coordinates=(40.4200, -3.6800),  # Tuple geopoint
        status=Status.ACTIVE
    )
    
    book = Product(
        name="Python Guide",
        price=45.00,
        category=books,
        tags={new, premium},  # Set
        coordinates={"latitude": 41.3851, "longitude": 2.1734},  # Dict geopoint
        status=Status.INACTIVE
    )
    
    # Store root
    store = Store(
        name="TechStore Madrid",
        location={"latitude": 40.4168, "longitude": -3.7038},  # Dict geopoint
        products=[laptop, mouse, book],  # Collection
        categories=[electronics, books],  # Collection con placeholder
        region="madrid",
        phone_numbers=["+34 91 123 4567", "+34 91 765 4321"],  # Lista simple
        operating_hours=(9, 21)  # Tuple simple
    )
    
    return store

# ===== TEST =====

def run_test():
    import json
    

    print("🚀 CREANDO DATOS...")
    store = create_test_data()
    
    
    print(json.dumps(Store.__document_schema__, indent=2, ensure_ascii=False))

    #print("\n📦 SERIALIZANDO...")
    #result = store.model_dump(mode="json")
    #print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\n🎯 RESULTADO:")
    
    
    #return result

if __name__ == "__main__":
    run_test()