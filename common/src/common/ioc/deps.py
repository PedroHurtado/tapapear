# common/ioc/deps.py
from dependency_injector.wiring import Provide
from typing import Type, TypeVar
from common.ioc.component import get_component_key
from fastapi import Depends

T = TypeVar("T")

def deps(cls: Type[T]):
    return Depends(Provide[get_component_key(cls)])
