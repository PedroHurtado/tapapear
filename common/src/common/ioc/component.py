# common/component.py
import inspect
from typing import Type, Dict, Any

component_registry: Dict[str, Dict[str, Any]] = {}

# common/ioc.py
from enum import Enum

class ProviderType(Enum):
    SINGLETON = "singleton"
    FACTORY = "factory"
    RESOURCE = "resource"


def get_component_key(cls: Type) -> str:
    return f"{cls.__module__}.{cls.__name__}"

def component(_cls=None, *, provider_type: ProviderType = ProviderType.SINGLETON):
    def wrap(cls):
        key = get_component_key(cls)
        if key in component_registry:
            raise ValueError(f"Duplicated component: {key}")

        # Registro inicial, se completará luego en build_container
        component_registry[key] = {
            "cls": cls,
            "provider_type": provider_type,
            "provider": None,
        }

        return cls

    # Permite usar @component y @component(...)
    return wrap if _cls is None else wrap(_cls)
