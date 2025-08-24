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
    _cls: Optional[Type] = None,
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
):
    """
    Decorador/función dual para registrar componentes en el IOC.
    
    Uso como decorador:
    @component
    class MyService: pass
    
    @component(provider_type=ProviderType.FACTORY)
    class MyFactory: pass
    
    Uso como función de registro manual:
    component(MyService)  # Registro directo
    component(MyService, provider_type=ProviderType.FACTORY)  # Con parámetros
    """
    component_registry = context.component_registry
    
    def register_component(target_cls: Type) -> Type:
        key = get_component_key(target_cls)
        if key in component_registry:
            raise ValueError(f"Duplicated component: {key}")

        component_registry[key] = {
            "cls": factory if factory is not None else target_cls,
            "provider_type": provider_type,
            "provider": None,
        }
        return target_cls

    # Caso 1: Uso como registro manual directo (component(MyClass))
    if _cls is not None:
        return register_component(_cls)
    
    # Caso 2: Uso como decorador con parámetros (@component(...))
    def decorator(target_cls: Type) -> Type:
        return register_component(target_cls)
    
    return decorator