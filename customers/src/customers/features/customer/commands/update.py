from common.server import build_router
from common.openapi import FeatureModel
from common.ioc import inject, deps
from common.confg import Config
router = build_router("customers")

class Response(FeatureModel):...
class Request(FeatureModel):...    

@router.put("", summary="Update Customer")
@inject
def controller(req:Request, config:Config=deps(Config))->Response:
    return Response