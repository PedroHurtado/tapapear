from enum import Enum
from common.infrastructure import Document, reference, geopoint, collection
from typing import Set, List, Tuple, Union
from common.infrastructure.document_schema_generator import (
    DocumentSchemaGenerator,
    generate_flat_schema,
)

from common.infrastructure.entity_decorator import entity

from pydantic.json_schema import GenerateJsonSchema

import json


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

@entity
class Store(Document):
    name: str
    location: Union[tuple, dict] = geopoint()
    products: List[Product] = collection()
    categories: List[Category] = collection("categories/{name}")
    region: str
    phone_numbers: List[str] = []  # Lista simple
    operating_hours: Tuple[int, int] = (9, 18)  # Tuple simple


#result = Store.model_json_schema(schema_generator=DocumentSchemaGenerator)

#result = generate_flat_schema(Store)

print(json.dumps(Store.__document_schema__,indent=2))
