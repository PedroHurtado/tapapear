from fastapi import APIRouter
from fastapi import APIRouter
from common.confg import Config, config


def build_router(tag: str, config: Config = config()) -> APIRouter:
    try:
        tag_conf = config.openapi.tags[tag]
    except KeyError:
        raise RuntimeError(f"La feature '{tag}' no existe en config.yaml")
    return APIRouter(prefix=tag_conf.prefix, tags=[tag])
