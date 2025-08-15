from common.infraestructure.firestore import RepositoryFirestore, get_db
from common.infraestructure.document import Document
from common.ioc import component
from common.mapper import get_mapper
from customers.domain.customer import Customer as CustomerDomain


class Customer(Document):
    name:str

mapper = get_mapper(CustomerDomain,Customer)

@component
class Repository(RepositoryFirestore[Customer]):
    def __init__(self, cls=Customer, db=get_db()):
        super().__init__(cls, db)

