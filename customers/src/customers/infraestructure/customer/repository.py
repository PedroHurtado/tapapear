from common.infraestructure.firestore import RepositoryFirestore, get_db
from common.infraestructure.document import Document
from common.ioc import component, ProviderType
from common.mapper import register_class
from customers.domain.customer import Customer as CustomerDomain

@component(provider_type=ProviderType.OBJECT)
class Customer(Document):
    name:str

register_class(CustomerDomain,Customer)

@component
class Repository(RepositoryFirestore[Customer]):
    def __init__(self, cls:Customer, db=get_db()):
        super().__init__(cls, db)

