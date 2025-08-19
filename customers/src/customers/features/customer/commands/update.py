from common.server import build_router
from common.openapi import FeatureModel


router = build_router("customers")

class Response(FeatureModel):...
class Request(FeatureModel):...    
@router.put("", summary="Update Customer")
def controller(req:Request)->Response:
    return Response