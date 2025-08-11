from fastapi import APIRouter
from pydantic import BaseModel
from common.ioc import component,deps

router = APIRouter(prefix="/customers")

class Request(BaseModel):...
class Response(BaseModel):...

@component
class Repository():...

@component
class Service():
    def __init__(self, repository:Repository=deps(Repository)):
        self._repository = repository
    async def __call__(self, req:Request):
        return Response()

@router.post("/")
async def controller(res:Request, service:Service=deps(Service)):
    return await service(), 201

