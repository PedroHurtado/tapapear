from typing import List
from pydantic import BaseModel

from common.server import build_router, EMPTY
from common.mediator import Command
from common.ioc import inject, deps
from common.confg import Config
from common.openapi import build_error_responses
from common.http import HttpClient


http = HttpClient("https://my-json-server.typicode.com/typicode/demo")


class Post(BaseModel):
    id: int
    title: str


class HpptPost:
    @http.get("/posts")
    async def query() -> List[Post]: ...
    @http.post("/posts")
    async def create(body:Post)->Post:...


router = build_router("customers")


class Request(Command): ...


@router.put(
    "", summary="Update Customer", status_code=204, responses=build_error_responses(409)
)
@inject
async def controller(req: Request, config: Config = deps(Config)):
    response = await HpptPost.create(Post(id=5,title="Post Jose Manuel"))
    print(response)

    #response = await HpptPost.query()
    #print(response)
    return EMPTY
