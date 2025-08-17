from functools import wraps
from typing import Callable, TypeVar
from dependency_injector.wiring import inject as _inject
from common.context import get_app_context

F = TypeVar("F", bound=Callable[..., object])
def inject(func:F)->F:   
    context = get_app_context()
    context.modules.add(func.__module__)
    return _inject(func)