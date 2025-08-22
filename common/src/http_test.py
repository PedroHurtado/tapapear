import asyncio
import json
from common.http import HttpClient, File as FileRequest
from common.ioc import component, ProviderType, container, inject, deps

from pydantic import BaseModel
from typing import List, Annotated

from fastapi import FastAPI, Form, UploadFile, File
from contextlib import asynccontextmanager
import threading


http = HttpClient("http://localhost:8081")

class Multipart(BaseModel):
    name: str
    file: FileRequest

class User(BaseModel):
    user:str
    password:str

class Post(BaseModel):
    id: int
    title: str

class FileInfo(BaseModel):
     filename: str
     size: int

@component(provider_type=ProviderType.OBJECT)
class PostHttp:

    @http.get("/posts/{id}")
    async def get(id: int) -> Post: ...

    @http.get("/posts")
    async def get_all() -> List[Post]: ...

    @http.post("/customers/multi")
    async def create(form_data: Multipart) -> FileInfo: ...

    @http.post("/customers/form")
    async def form(form: User):...

@inject
async def main(http: PostHttp = deps(PostHttp)):

    data = {"id": 1, "name": "Pedro"}

    # 🔑 Convertir dict -> JSON -> bytes
    json_bytes = json.dumps(data).encode("utf-8")

    # Crear el objeto File
    file = FileRequest(
        content=json_bytes, filename="data.json", content_type="application/json"
    )

    # Pasarlo al Multipart
    multipart = Multipart(name="Pedro", file=file)

    # Enviar al endpoint
    file_info = await http.create(multipart)

    await http.form(User(user="pedro", password="1234"))
    print(file_info)


if __name__ == "__main__":
    container.wire([__name__])
    asyncio.run(main())
    

