from typing import Dict, Any, Type
from functools import wraps
from pydantic import BaseModel


def agregate_root(cls):
    """
    Decorador que genera esquema flat optimizado para entidades root.
    
    Aplica SOLO a Document classes principales (Store, User, Order, etc.)
    NO usar en: Embeddables, Value Objects o entidades hijas.
    
    Usage:
        @entity
        class Store(Document):
            name: str
            products: List[Product] = collection()
        
        # Acceso al schema: Store.__document_schema__
    """
    # Importar aquí para evitar circular imports
    from .document_schema_generator import generate_flat_schema
    
    # Generar y guardar el esquema flat
    cls.__document_schema__ = generate_flat_schema(cls)
    
    return cls