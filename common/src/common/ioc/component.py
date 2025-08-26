from typing import Type, Callable, Optional, get_origin, get_args
from enum import Enum
from common.context import context


class ProviderType(Enum):
    SINGLETON = "singleton"
    FACTORY = "factory"
    RESOURCE = "resource"
    OBJECT = "object"
    LIST = "list"


def get_component_key(cls: Type) -> str:
    # Manejar tipos especiales como List[Type]
    if hasattr(cls, '__origin__') and get_origin(cls) is list:
        # Para List[Type], usar "List_ModuleName_TypeName"
        args = get_args(cls)
        if args:
            base_type = args[0]
            return f"List_{base_type.__module__}_{base_type.__name__}".replace(".", "_")
        else:
            raise ValueError(f"List type must have arguments: {cls}")
    
    # Caso normal para clases regulares
    return f"{cls.__module__}.{cls.__name__}".replace(".", "_")


def component(
    _cls: Optional[Type] = None,
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
    value: Optional[object] = None,
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
    component(List[MyService], provider_type=ProviderType.LIST)  # Para listas
    component(AppContainer, provider_type=ProviderType.OBJECT, value=container)  # Para instancias
    component(provider_type=ProviderType.OBJECT)  # Para Tipos
    """
    component_registry = context.component_registry
    
    def register_component(target_cls: Type) -> Type:
        key = get_component_key(target_cls)
        if key in component_registry:
            raise ValueError(f"Duplicated component: {key}")

        # Validaciones de consistencia
        if provider_type in (ProviderType.SINGLETON, ProviderType.FACTORY) and factory is not None and value is not None:
            raise ValueError(f"'factory' y 'value' no pueden usarse juntos para {key}")     
            
        if provider_type in (ProviderType.SINGLETON, ProviderType.FACTORY) and value is not None:
            raise ValueError(f"'value' no es válido para provider_type={provider_type.value} en {key}")
        
        if provider_type == ProviderType.LIST and (factory is not None or value is not None):
            raise ValueError(f"'factory' y 'value' no son válidos para provider_type=LIST en {key}")

        # Registro
        component_registry[key] = {
            "cls": factory if factory is not None else target_cls,
            "provider_type": provider_type,
            "provider": None,
            "value": value if provider_type == ProviderType.OBJECT and value else target_cls,
        }
        return target_cls

    # Caso 1: Uso como registro manual directo (component(MyClass))
    if _cls is not None:
        return register_component(_cls)
    
    # Caso 2: Uso como decorador con parámetros (@component(...))
    def decorator(target_cls: Type) -> Type:
        return register_component(target_cls)
    
    return decorator
