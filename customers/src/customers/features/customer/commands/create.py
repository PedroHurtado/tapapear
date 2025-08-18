from fastapi import APIRouter
from common.ioc import component, deps, inject
from common.infraestructure.repository import InjectsRepo, Add
from common.openapi import FeatureModel
from customers.domain.customer import Customer, TaxType
from customers.infraestructure.customer import Repository as repo, mapper
from uuid import uuid4, UUID
from datetime import datetime

router = APIRouter(prefix="/customers", tags=["Customer"])


class Request(FeatureModel):
    name: str


class Response(FeatureModel):
    id: UUID
    name: str


@component
class Repository(InjectsRepo, Add[Customer]):
    def __init__(self, repo: repo, mapper=mapper):
        super().__init__(repo, mapper)


@component
class Service:
    def __init__(self, repository: Repository):
        self._repository = repository

    async def __call__(self, req: Request)->Response:

        tax_type = TaxType("", "")
        customer = Customer.create(
            uuid4(), req.name, "", "", "", datetime.now(), 200, tax_type, "52"
        )

        await self._repository.create_async(customer)

        return mapper.to(Response).map(customer)


@router.post("", status_code=201, summary="Create Customer")
@inject
async def controller(req: Request, service: Service = deps(Service)) -> Response:
    return await service(req)
