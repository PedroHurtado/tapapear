# SOLUCIÓN QUE FUNCIONA: Usar typing.TYPE_CHECKING y overload
from dependency_injector.wiring import Provide
from typing import Type, TypeVar, overload, TYPE_CHECKING
from common.ioc.component import get_component_key
from fastapi import Depends

T = TypeVar("T")

def deps(cls: Type[T]) -> T:
   return Depends(Provide[get_component_key(cls)])


