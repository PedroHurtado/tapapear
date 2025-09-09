from typing import List
from pydantic import BaseModel

from common.server import build_router, EMPTY
from common.mediator import Command
from common.ioc import inject, deps
from common.openapi import build_error_responses
from common.http import HttpClient
from common.ioc import component,inject,deps, ProviderType
from common.mediator import CommandHadler, Mediator 


router = build_router("customers")

http = HttpClient("https://my-json-server.typicode.com/typicode/demo")

class Post(BaseModel):
    id: int
    title: str


class HpptPost:
    @http.get("/posts")
    async def query() -> List[Post]: ...
    @http.post("/posts")
    async def create(body:Post)->Post:...

component(HpptPost, provider_type=ProviderType.OBJECT, value=HpptPost)




class Request(Command): ...

@component
class Service(CommandHadler[Request]):
    def __init__(self,http_post:HpptPost):
        self._http_post = http_post
    async def handler(self, command:Request):
        #response = await self._http_post.create(Post(id=5,title="Jose Manuel Hurtado"))
        response = await self._http_post.create()
        

@router.put(
    "", summary="Update Customer", status_code=204, responses=build_error_responses(409)
)
@inject
async def controller(req: Request, mediator:Mediator=deps(Mediator)):    
    await mediator.send(req)
    return EMPTY
