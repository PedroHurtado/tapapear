
from fastapi import FastAPI, Depends, Path, Body
from pydantic import BaseModel

app = FastAPI()

class EntityUpdate(BaseModel):
    name: str
    description: str

class EntityWithId(EntityUpdate):
    id: int

def build_entity_with_id(
    id: int = Path(...),
    body: EntityUpdate = Body(...)
) -> EntityWithId:
    return EntityWithId(id=id, **body.model_dump())

@app.put("/entity/{id}")
async def update_entity(entity: EntityWithId = Depends(build_entity_with_id))->EntityWithId:
    return entity

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, port=8080)
