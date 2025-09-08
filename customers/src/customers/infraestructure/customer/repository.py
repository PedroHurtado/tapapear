from common.infraestructure.firestore import RepositoryFirestore
from common.infraestructure.document import Document
from common.ioc import component, ProviderType
from common.mapper import mapper_class
from customers.domain.customer import Customer as CustomerDomain

@component(provider_type=ProviderType.OBJECT)
class Customer(Document):
    name:str

mapper_class(CustomerDomain,Customer)

@component
class Repository(RepositoryFirestore[Customer]):...
 
