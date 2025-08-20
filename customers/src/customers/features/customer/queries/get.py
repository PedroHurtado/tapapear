from common.server import build_router
from common.security import allow_anonymous

router = build_router("customers")
@router.get("", summary="get customers")
@allow_anonymous
async def controller():
    return ""
