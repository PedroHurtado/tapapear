from typing import Set, List
from common.infrastructure import Document, reference, collection
from common.util import get_id




class Article(Document):
    name: str


class Item(Document): ...


class Order(Document):
    # 🔹 Subcolección explícita con {id}
    items_list_by_id: List[Item] = collection("items/{id}")

    # 🔹 Subcolección con plural automático
    items_list_collection: List[Item] = collection()

    items_list: List[Item]


    items_set_by_id: Set[Item] = collection("items/{id}")

    # 🔹 Subcolección con plural automático
    items_set_collection: Set[Item] = collection()

    # 🔹 Array normal (sin collection, se guarda como array en Firestore)
    items_set: Set[Item] #Set[Item] exception
    

    name: str
    article: Article = reference()


class User(Document):
    order: Order = collection()


items = [Item(id=get_id()), Item(id=get_id()), Item(id=get_id()), Item(id=get_id())]
article = Article(id=get_id(), name="tomate")
# Crear instancias
order = Order(
    id=get_id(),
    article=article,
    name="Jose Manuel",
    
    items_list_by_id=items,
    items_list_collection=items,
    items_list=items,

    items_set_by_id=set(items),
    items_set_collection=set(items),
    items_set=set(items)
    
)
user = User(id=get_id(), order=order)
print(user.model_dump_json())
