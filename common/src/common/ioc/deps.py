# common/deps.py
from dependency_injector.wiring import Provide
from typing import Type, Annotated, TypeVar
from common.ioc.component import get_component_key

T = TypeVar("T")

def deps(cls: Type[T]):
    return Provide[get_component_key(cls)]
