from typing import Type, Callable, Optional
from enum import Enum
from common.context import context


class ProviderType(Enum):
    SINGLETON = "singleton"
    FACTORY = "factory"
    RESOURCE = "resource"
    OBJECT = "object"


def get_component_key(cls: Type) -> str:
    return f"{cls.__module__}.{cls.__name__}".replace(".", "_")

def component(
    _cls=None,
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
):
    component_registry =context.component_registry
    def wrap(cls):
        key = get_component_key(cls)
        if key in component_registry:
            raise ValueError(f"Duplicated component: {key}")

        # Registro inicial, se completará luego en build_container
        component_registry[key] = {
            "cls": factory if factory is not None else cls,
            "provider_type": provider_type,
            "provider": None,
        }

        return cls

    # Permite usar @component y @component(...)
    return wrap if _cls is None else wrap(_cls)
