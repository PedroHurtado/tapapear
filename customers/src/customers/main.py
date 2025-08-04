from uuid import UUID, uuid4
from common.infraestructure import(
    InjectsRepo,
    Get,
    Document    
)
from typing import Any,Optional
from common.domain import BaseEntity
from common import get_mapper

class Foo(Document):...
class FooDomain(BaseEntity):...
mapper = get_mapper(FooDomain,Foo)


class SimpleTestRepository:
    """Repositorio de prueba simple."""
    
    def create(self, entity):
        print(f"create - Tipo: {type(entity).__name__}, Objeto: {entity}")
    
    def get(self, id: UUID):
        print(f"get - Tipo: {type(id).__name__}, Objeto: {id}")
        return Foo(id=id)
    
    def update(self, entity):
        print(f"update - Tipo: {type(entity).__name__}, Objeto: {entity}")
    
    def remove(self, entity):
        print(f"remove - Tipo: {type(entity).__name__}, Objeto: {entity}")
    
    def find_by_field(self, field: str, value: Any, limit: Optional[int] = None):
        print(f"find_by_field - field: {field} (tipo: {type(field).__name__}), value: {value} (tipo: {type(value).__name__}), limit: {limit}")
        return [Foo()]  # Siempre devuelve una lista con un objeto Foo


# Repo concreto
class BarRepo(InjectsRepo, Get[FooDomain]):
    pass

bar_repo = BarRepo(SimpleTestRepository(),mapper)
foo_domain= bar_repo.get(uuid4())

print(foo_domain)








