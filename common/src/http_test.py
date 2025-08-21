import asyncio
from common.http import HttpClient
from common.ioc import component,ProviderType, container, inject,deps
from pydantic import BaseModel
from typing import List

http = HttpClient("https://my-json-server.typicode.com/typicode/demo")

class Post(BaseModel):
    id:int
    title:str

@component(provider_type=ProviderType.OBJECT)
class PostHttp:
    
    @http.get("/posts/{id}")
    async def get(id:int)->Post:...

    @http.get("/posts")
    async def get_all()->List[Post]:...


@inject
async def main(http:PostHttp = deps(PostHttp)):    
    post = await http.get(1)
    posts = await http.get_all()
    print(posts)
    print(post)

if __name__ == "__main__":
    container.wire([__name__])
    asyncio.run(main())
