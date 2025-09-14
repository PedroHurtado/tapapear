from common.http import HttpClient
from pydantic import BaseModel
from typing import List
from common.ioc import component,ProviderType

http = HttpClient("https://my-json-server.typicode.com/typicode/demo")

class Post(BaseModel):
    id:int
    title:str

@component(provider_type = ProviderType.OBJECT)
class PostService:
    @staticmethod
    @http.get("/posts")
    async def query()->List[Post]:...
