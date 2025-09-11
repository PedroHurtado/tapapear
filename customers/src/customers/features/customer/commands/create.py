from common.ioc import component, deps, inject
from common.infrastructure.repository import AbstractRepository, Add
from common.server import build_router
from common.mapper import Mapper
from common.util import get_id,get_now,ID
from common.openapi import FeatureModel
from common.mediator import Mediator, Command, CommandHadler
from customers.domain.customer import Customer, TaxType
from customers.infrastructure.customer import RepositoryCustomer

router = build_router("customers")




class Request(Command):
    name: str

class Response(FeatureModel):
    id: ID
    name: str


@component
class Repository(AbstractRepository[RepositoryCustomer], Add[Customer]):
    pass


@component
class Service(CommandHadler[Request]):

    def __init__(self, repository: Repository, mapper: Mapper):
        self._repository = repository
        self._mapper = mapper

    async def handler(self, req: Request) -> Response:

        tax_type = TaxType("", "")
        customer = Customer.create(
            get_id(), req.name, "", "", "", get_now(), 200, tax_type, "52"
        )        
        await self._repository.create(customer)
        return self._mapper.to(Response).map(customer)


@router.post("", status_code=201, summary="Create Customer pirolino")
@inject
async def controller(req: Request, mediator: Mediator = deps(Mediator)) -> Response:
    return await mediator.send(req)
