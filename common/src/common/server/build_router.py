from common.confg import OpenApiConfig,config
from fastapi import APIRouter

from fastapi import APIRouter

def build_router( tag: str,config: OpenApiConfig=config().openapi) -> APIRouter:
    try:
        tag_conf = config.tags[tag]
    except KeyError:
        raise RuntimeError(f"La feature '{tag}' no existe en config.yaml")
    
    return APIRouter(
        prefix=tag_conf.prefix,
        tags=[tag]
    )
