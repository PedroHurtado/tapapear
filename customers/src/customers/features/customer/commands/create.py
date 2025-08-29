from common.ioc import component, deps, inject
from common.infraestructure.repository import AbstractRepository, Add
from common.server import build_router
from common.mapper import Mapper
from common.util import get_id
from common.mediator import Mediator,Command, CommandHadler
from customers.domain.customer import Customer, TaxType
from customers.infraestructure.customer import Repository as RepositoryCustomer
from pydantic import BaseModel
from uuid import UUID
from datetime import datetime

router = build_router("customers")


class Request(Command):
    name: str


class Response(BaseModel):
    id: UUID
    name: str

@component
class Repository(AbstractRepository[RepositoryCustomer], Add[Customer]):
    pass    

@component
class Service(CommandHadler[Request]):

    def __init__(self,repository: Repository, mapper: Mapper):
        self._repository = repository
        self._mapper = mapper

    async def handler(self, req:Request)->Response:        
        
        tax_type = TaxType("", "")
        customer = Customer.create(
            get_id(), req.name, "", "", "", datetime.now(), 200, tax_type, "52"
        )
        await self._repository.create(customer)
        return self._mapper.to(Response).map(customer)
        

@router.post("", status_code=201, summary="Create Customer")
@inject
async def controller(req: Request, mediator:Mediator = deps(Mediator)) -> Response:
    return await mediator.send(req)
