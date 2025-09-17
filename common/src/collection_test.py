from typing import Set,List
from common.infrastructure import Document,reference,collection
from common.util import get_id
class Article(Document): 
    name:str

class Item(Document): ...


class Order(Document):  
    items: Set[Item] = collection()
    name:str
    article: Article = reference()


class User(Document): 
    order: Order = collection()
items = [Item(id=get_id()),Item(id=get_id()),Item(id=get_id()),Item(id=get_id())]
article = Article(id=get_id(),name="tomate")
# Crear instancias
order = Order(id=get_id(), article=article, items=items, name="Jose Manuel")
user = User(id=get_id(), order=order)

print(user.model_dump_json())