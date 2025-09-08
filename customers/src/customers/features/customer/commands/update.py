from common.server import build_router,empty
from common.mediator import Command
from common.ioc import inject, deps
from common.confg import Config
from common.openapi import build_error_responses
from common.server import empty


router = build_router("customers")

class Request(Command):...    


@router.put("", summary="Update Customer", status_code=204, responses=build_error_responses(400,409))
@inject
def controller(req:Request, config:Config=deps(Config)):
    return empty()