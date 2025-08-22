from common.server import build_router
from common.security import allow_anonymous
from common.openapi import FeatureModel
from typing import Annotated
from fastapi import Form, UploadFile, File, Depends, Response

router = build_router("customers")


@router.get("", summary="get customers")
@allow_anonymous
async def controller():
    return ""


class MultiModel(FeatureModel):
    name: str
    file: UploadFile  # este campo no se valida en pydantic, pero sí lo recibes

    @classmethod
    def as_form(
        cls,
        name: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ):
        return cls(name=name, file=file)


@router.post("/multi")
@allow_anonymous
async def multi(data: Annotated[MultiModel, Depends(MultiModel.as_form)]):

    contents = bytearray()
    
    while chunk := await data.file.read(1024 * 1024):  # 1MB
        contents.extend(chunk)

    return {
        "filename": data.file.filename,
        "size": len(contents),
    }
    
@router.post("/form", status_code=204)
@allow_anonymous
async def form(
                user:Annotated[str,Form()],
                password:Annotated[str,Form()]
               ):
        return Response(status_code=204)
     
