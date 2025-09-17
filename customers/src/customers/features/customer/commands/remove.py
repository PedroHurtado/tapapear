from common.server import build_router, EMPTY
from common.mediator import Command, CommandHadler, Mediator
from common.mapper import Mapper
from common.security import authorize
from common.util import ID
from common.infrastructure import AbstractRepository, Remove
from common.ioc import component, inject, deps
from customers.infrastructure.customer import RepositoryCustomer
from customers.domain.customer import Customer

router = build_router("customers")


class Request(Command):
    id: ID


@component
class Repository(AbstractRepository[RepositoryCustomer], Remove[Customer]): ...


@component
class Service(CommandHadler[Request]):
    def __init__(self, repository: Repository, mapper: Mapper):
        self._repository = repository
        self._mapper = mapper

    async def handler(self, command: Request):

        customer = await self._repository.get(command.id)

        await self._repository.delete(customer)

        return EMPTY


@router.delete("/{id}", status_code=204, summary="Remove Customer")
@authorize(["Admin"])
@inject
async def controller(id: ID, mediator: Mediator = deps(Mediator)):
    return await mediator.send(Request(id=id))
