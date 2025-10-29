"""
Test Integrado - MixinSerializer

Este test funciona con el código REAL del proyecto:
- Usa las clases Document, reference, collection, geopoint
- Usa el decorator @aggregate_root
- Genera el JSON usando model_dump_aggregate_root()
- Valida el resultado automáticamente
- Compara con versión anterior si existe

USO:
    python test_integrado.py                    # Usa código actual
    python test_integrado.py --use-v2           # Usa document_v2.py
    python test_integrado.py --compare          # Compara ambas versiones
"""

import json
import os
import sys
import argparse
from pathlib import Path
from typing import List, Set, Tuple, Union
from enum import Enum

# ===== IMPORTAR CLASES REALES DEL PROYECTO =====

try:
    # Intentar importar del código del proyecto
    # Ajusta estos imports según tu estructura de directorios
    from common.infrastructure import Document, reference, collection, geopoint
    from common.infrastructure.agregate_root import agregate_root
    USING_REAL_CODE = True
except ImportError:
    print("⚠️  No se pudo importar del proyecto. Ejecuta desde el directorio correcto.")
    print("   O ajusta los imports en el archivo test_integrado.py")
    sys.exit(1)


# ===== MODELO DE DATOS =====

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
    tags: Set[Tag] = set()
    coordinates: Union[tuple, dict] = geopoint()
    status: Status


@agregate_root
class Store(Document):
    name: str
    location: Union[tuple, dict] = geopoint()
    products: List[Product] = collection()
    categories: List[Category] = collection("categories/{name}")
    region: str
    phone_numbers: List[str] = []
    operating_hours: Tuple[int, int] = (9, 18)


# ===== CREACIÓN DE DATOS =====

def create_test_data():
    """Crea datos de prueba completos"""
    
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
        tags={premium, new},
        coordinates=(40.4168, -3.7038),
        status=Status.ACTIVE
    )
    
    mouse = Product(
        name="Wireless Mouse", 
        price=25.50,
        category=electronics,
        tags={sale},
        coordinates=(40.4200, -3.6800),
        status=Status.ACTIVE
    )
    
    book = Product(
        name="Python Guide",
        price=45.00,
        category=books,
        tags={new, premium},
        coordinates={"latitude": 41.3851, "longitude": 2.1734},
        status=Status.INACTIVE
    )
    
    # Store
    store = Store(
        name="TechStore Madrid",
        location={"latitude": 40.4168, "longitude": -3.7038},
        products=[laptop, mouse, book],
        categories=[electronics, books],
        region="madrid",
        phone_numbers=["+34 91 123 4567", "+34 91 765 4321"],
        operating_hours=(9, 21)
    )
    
    return store


# ===== VALIDACIONES =====

class ValidationResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.passed = 0
        self.failed = 0
    
    def add_error(self, msg: str):
        self.errors.append(msg)
        self.failed += 1
    
    def add_warning(self, msg: str):
        self.warnings.append(msg)
    
    def add_pass(self):
        self.passed += 1
    
    def is_success(self) -> bool:
        return len(self.errors) == 0
    
    def print_summary(self):
        print(f"\n{'='*70}")
        print("📊 RESUMEN DE VALIDACIÓN")
        print(f"{'='*70}")
        print(f"✅ Pasadas:     {self.passed}")
        print(f"❌ Fallidas:    {self.failed}")
        print(f"⚠️  Advertencias: {len(self.warnings)}")
        
        if self.errors:
            print(f"\n❌ ERRORES ({len(self.errors)}):")
            for error in self.errors:
                print(f"  {error}")
        
        if self.warnings:
            print(f"\n⚠️  ADVERTENCIAS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  {warning}")
        
        print(f"{'='*70}")
        if self.is_success():
            print("✅ TODOS LOS TESTS PASARON")
        else:
            print("❌ ALGUNOS TESTS FALLARON")
        print(f"{'='*70}")


def validate_json(data: dict) -> ValidationResult:
    """Ejecuta todas las validaciones"""
    result = ValidationResult()
    
    print(f"\n{'='*70}")
    print("🧪 EJECUTANDO VALIDACIONES")
    print(f"{'='*70}")
    
    # 1. Store root
    print("\n🔍 Validando Store root...")
    if "id" in data and "path" in data["id"]:
        if data["id"]["path"].startswith("stores/"):
            result.add_pass()
            print("  ✅ Store.id correcto")
        else:
            result.add_error(f"Store.id incorrecto: {data['id']['path']}")
    else:
        result.add_error("Store.id falta o malformado")
    
    # 2. Products collection (reference_field='id' por defecto)
    print("\n🔍 Validando Products collection (reference_field='id')...")
    if "products" in data and isinstance(data["products"], list) and len(data["products"]) > 0:
        product = data["products"][0]
        
        # 2.1 ID con hierarchy (porque reference_field='id')
        if "id" in product and "path" in product["id"]:
            path = product["id"]["path"]
            if "stores/" in path and "products/" in path:
                result.add_pass()
                print(f"  ✅ Product.id con hierarchy: {path[:50]}...")
            else:
                result.add_error(f"Product.id sin hierarchy: {path}")
        else:
            result.add_error("Product.id falta o malformado")
        
        # 2.2 Category SOLO path (es una reference, no collection)
        if "category" in product:
            category = product["category"]
            if isinstance(category, dict):
                cat_keys = set(category.keys())
                if cat_keys == {"path"}:
                    result.add_pass()
                    print("  ✅ Product.category solo tiene 'path'")
                else:
                    extra = cat_keys - {"path"}
                    result.add_error(f"Product.category tiene campos extras: {extra}")
            else:
                result.add_error(f"Product.category tipo incorrecto: {type(category)}")
        else:
            result.add_error("Product.category no existe")
        
        # 2.3 Tags completos (Set de Documents, no collection del aggregate)
        if "tags" in product and isinstance(product["tags"], list) and len(product["tags"]) > 0:
            tag = product["tags"][0]
            if "id" in tag and "name" in tag and "color" in tag:
                result.add_pass()
                print("  ✅ Tags tienen todos los campos")
            else:
                result.add_error(f"Tag incompleto: {tag}")
        else:
            result.add_warning("No hay tags para validar")
    else:
        result.add_error("Products collection vacía o malformada")
    
    # 3. Categories collection (reference_field='name')
    print("\n🔍 Validando Categories collection (reference_field='name')...")
    if "categories" in data and isinstance(data["categories"], list) and len(data["categories"]) > 0:
        category = data["categories"][0]
        
        # 3.1 'name' como CollectionReference (porque reference_field='name')
        if "name" in category:
            name_value = category["name"]
            if isinstance(name_value, dict) and "path" in name_value:
                path = name_value["path"]
                if "stores/" in path and "categories/" in path:
                    result.add_pass()
                    print(f"  ✅ Category.name con hierarchy: {path[:50]}...")
                else:
                    result.add_error(f"Category.name sin hierarchy: {path}")
            else:
                result.add_error(f"Category.name debe ser CollectionReference, es: {type(name_value)}")
        else:
            result.add_error("Category.name no existe")
        
        # 3.2 'id' como UUID simple (porque reference_field='name', no 'id')
        if "id" in category:
            id_value = category["id"]
            if isinstance(id_value, str):
                # Es un UUID simple (correcto)
                result.add_pass()
                print(f"  ✅ Category.id es UUID simple: {id_value[:8]}...")
            elif isinstance(id_value, dict) and "path" in id_value:
                result.add_error(f"Category.id NO debe ser DocumentId cuando reference_field='name': {id_value}")
            else:
                result.add_error(f"Category.id tiene formato incorrecto: {type(id_value)}")
        else:
            result.add_error("Category.id no existe")
        
        # 3.3 Campo 'description' existe
        if "description" in category:
            result.add_pass()
            print("  ✅ Category tiene description")
        else:
            result.add_error("Category falta description")
    else:
        result.add_error("Categories collection vacía o malformada")
    
    return result


# ===== COMPARACIÓN =====

def compare_jsons(old_file: str, new_file: str):
    """Compara dos JSONs y muestra diferencias"""
    
    if not os.path.exists(old_file):
        print(f"\nℹ️  No hay archivo anterior ({old_file}) para comparar")
        return
    
    print(f"\n{'='*70}")
    print("📊 COMPARANDO VERSIONES")
    print(f"{'='*70}")
    
    with open(old_file, 'r') as f:
        old = json.load(f)
    with open(new_file, 'r') as f:
        new = json.load(f)
    
    # Tamaños
    old_size = len(json.dumps(old))
    new_size = len(json.dumps(new))
    diff_pct = ((new_size - old_size) / old_size) * 100 if old_size > 0 else 0
    
    print(f"\n📏 Tamaño:")
    print(f"  Anterior: {old_size:,} bytes")
    print(f"  Nuevo:    {new_size:,} bytes")
    print(f"  Cambio:   {diff_pct:+.1f}%")
    
    # Comparar Product[0] si existe
    if ("products" in old and len(old["products"]) > 0 and 
        "products" in new and len(new["products"]) > 0):
        
        old_prod = old["products"][0]
        new_prod = new["products"][0]
        
        print(f"\n🔍 Product[0]:")
        
        # IDs
        old_id = old_prod.get("id", {}).get("path", "N/A")
        new_id = new_prod.get("id", {}).get("path", "N/A")
        print(f"\n  ID:")
        print(f"    Anterior: {old_id}")
        print(f"    Nuevo:    {new_id}")
        
        if "stores/" in new_id and "products/" in new_id:
            print(f"    ✅ Nuevo tiene hierarchy")
        
        # Category
        old_cat = old_prod.get("category", {})
        new_cat = new_prod.get("category", {})
        old_keys = set(old_cat.keys())
        new_keys = set(new_cat.keys())
        
        print(f"\n  Category:")
        print(f"    Anterior: {sorted(old_keys)}")
        print(f"    Nuevo:    {sorted(new_keys)}")
        
        if old_keys != new_keys:
            removed = old_keys - new_keys
            if removed:
                print(f"    ✅ Removidos: {removed}")
    
    # Comparar Categories si existen
    if ("categories" in old and len(old["categories"]) > 0 and 
        "categories" in new and len(new["categories"]) > 0):
        
        old_cat = old["categories"][0]
        new_cat = new["categories"][0]
        
        print(f"\n🔍 Categories[0]:")
        
        # ID
        old_id = old_cat.get("id")
        new_id = new_cat.get("id")
        print(f"\n  ID:")
        print(f"    Anterior: {old_id}")
        print(f"    Nuevo:    {new_id}")
        
        if isinstance(new_id, str):
            print(f"    ✅ Nuevo es UUID simple (reference_field='name')")
        
        # Name
        old_name = old_cat.get("name")
        new_name = new_cat.get("name")
        print(f"\n  Name:")
        print(f"    Anterior: {old_name}")
        print(f"    Nuevo:    {new_name}")
        
        if isinstance(new_name, dict) and "path" in new_name:
            print(f"    ✅ Nuevo es CollectionReference (reference_field='name')")


# ===== MAIN =====

def main():
    parser = argparse.ArgumentParser(description='Test integrado MixinSerializer')
    parser.add_argument('--use-v2', action='store_true', 
                       help='Usar document_v2.py en lugar del actual')
    parser.add_argument('--compare', action='store_true',
                       help='Comparar actual vs v2')
    parser.add_argument('--output', default='Resultato_test.json',
                       help='Archivo de salida (default: Resultato_test.json)')
    
    args = parser.parse_args()
    
    print("🚀 TEST INTEGRADO - MixinSerializer")
    print(f"{'='*70}")
    
    if args.use_v2:
        print("ℹ️  Usando document_v2.py (NUEVA VERSIÓN)")
    else:
        print("ℹ️  Usando código actual del proyecto")
    
    # 1. Crear datos
    print(f"\n📦 Creando datos de prueba...")
    store = create_test_data()
    print(f"✅ Store creado: {store.name}")
    print(f"   - Products: {len(store.products)}")
    print(f"   - Categories: {len(store.categories)}")
    
    # 2. Serializar
    print(f"\n⚙️  Serializando con model_dump_aggregate_root()...")
    try:
        result = store.model_dump_aggregate_root(mode="json")
        print("✅ Serialización completada")
    except Exception as e:
        print(f"❌ Error en serialización: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # 3. Guardar
    output_file = args.output
    print(f"\n💾 Guardando en {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    size = os.path.getsize(output_file)
    print(f"✅ Archivo guardado ({size:,} bytes)")
    
    # 4. Validar
    validation = validate_json(result)
    validation.print_summary()
    
    # 5. Comparar si se solicita
    if args.compare or os.path.exists("Resultato.json"):
        compare_jsons("Resultato.json", output_file)
    
    # 6. Mostrar preview
    print(f"\n📄 Preview del JSON (primeras 40 líneas):")
    print("-" * 70)
    lines = json.dumps(result, indent=2, ensure_ascii=False).split('\n')
    for line in lines[:40]:
        print(line)
    if len(lines) > 40:
        print("...")
    print("-" * 70)
    
    # 7. Resumen final
    print(f"\n{'='*70}")
    print("✅ TEST COMPLETADO")
    print(f"{'='*70}")
    print(f"Archivo: {output_file}")
    print(f"Tamaño:  {size:,} bytes")
    print(f"Status:  {'✅ PASS' if validation.is_success() else '❌ FAIL'}")
    print(f"{'='*70}")
    
    return 0 if validation.is_success() else 1


if __name__ == "__main__":
    sys.exit(main())