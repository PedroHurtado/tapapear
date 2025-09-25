from common.domain import BaseEntity
from common.infrastructure import Document
from common.util import ID,get_id
from common.mapper import mapper
from typing import Set

class Ingredient(BaseEntity):
    def __init__(self, id:ID,name:str):
        super().__init__(id)
        self._name = name
    @property
    def name(self):
        return self._name
    

class Pizza(BaseEntity):
    def __init__(self, id:ID, ingredients:Set):
        super().__init__(id)
        self._ingredients =  ingredients
    @property
    def ingredients(self):
        return self._ingredients
        


class IngredientDocument(Document):
    name:str

class PizzaDocument(Document):
    ingredients:Set[IngredientDocument]

def test():
    ingredient_document = IngredientDocument(id=get_id(),name="tomate")
    pizza_document = PizzaDocument(id=get_id(), ingredients={ingredient_document})

    pizza = mapper.to(Pizza).map(pizza_document)
    mapper.to(PizzaDocument).map(pizza)

if __name__ == '__main__':
    test()
