"""
Script de prueba para el ChangeTracker con casos reales
"""

from typing import Set, List
from common.infrastructure import Document, reference, collection
from common.util import get_id

from common.infrastructure.unit_of_work import ChangeTracker,ChangeType, VerboseConsoleDialect
# Importar nuestro módulo de tracking


class Article(Document):
    name: str


class Item(Document): 
    pass  # Item vacío por simplicidad


class Order(Document):
    items:Set[Item] = collection()
    
    name: str
    article: Article = reference()


class User(Document):
    order: Order = collection()


def test_change_tracker():
    """Prueba completa del ChangeTracker"""
    
    print("🧪 INICIANDO TESTS DEL CHANGE TRACKER")
    print("="*80)
    
    # ============== SETUP ==============
    
    # Crear datos de prueba
    items = [Item(id=get_id()), Item(id=get_id()), Item(id=get_id()), Item(id=get_id())]
    article = Article(id=get_id(), name="tomate")
    
    # Crear instancias
    order = Order(
        id=get_id(),
        article=article,
        name="Jose Manuel",        
        items=items
    )
    user = User(id=get_id(), order=order)
    
    print(f"📋 Datos creados:")
    print(f"   👤 User ID: {user.id}")
    print(f"   📦 Order ID: {order.id}")
    print(f"   📰 Article ID: {article.id}")
    print(f"   📝 Items: {len(items)} items")
    
    # ============== TEST 1: CREATE ==============
    
    print(f"\n{'TEST 1: CREATE OPERATION':=^80}")
    
    # Crear tracker con dialecto de consola
    console_dialect = VerboseConsoleDialect()
    tracker = ChangeTracker(console_dialect)
    
    # Trackear como ADDED (operación CREATE)
    tracker.track_entity(user, ChangeType.ADDED)
    
    print(f"✅ Usuario trackeado como ADDED")
    print(f"🔍 Tracked entities: {len(tracker._tracked_entities)}")
    
    # Ejecutar save_changes
    print(f"\n🚀 Ejecutando save_changes()...")
    tracker.save_changes()
    
    # ============== TEST 2: DELETE ==============
    
    print(f"\n{'TEST 2: DELETE OPERATION':=^80}")
    
    # Crear nuevo tracker para DELETE
    tracker2 = ChangeTracker(console_dialect)
    
    # Trackear como DELETED
    tracker2.track_entity(user, ChangeType.DELETED)
    
    print(f"✅ Usuario trackeado como DELETED")
    
    # Ejecutar save_changes
    print(f"\n🚀 Ejecutando save_changes()...")
    tracker2.save_changes()
    
    # ============== TEST 3: VERIFICAR SERIALIZACIÓN ==============
    
    print(f"\n{'TEST 3: SERIALIZATION CHECK':=^80}")
    
    # Verificar cómo se serializa el usuario
    user_data = user.model_dump(context={"is_root": True})
    
    #print(f"📄 Estructura serializada del User:")
    #import json
    #print(json.dumps(user_data, indent=2, default=str))





if __name__ == "__main__":
    try:
        test_change_tracker()        
        
        print(f"\n{'🎉 TODOS LOS TESTS COMPLETADOS EXITOSAMENTE':=^80}")
        
    except Exception as e:
        print(f"\n{'❌ ERROR EN LOS TESTS':=^80}")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()