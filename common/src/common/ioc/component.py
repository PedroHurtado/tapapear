from typing import Type, Callable, Optional, get_origin, get_args, TypeVar, Union, overload
from enum import Enum
from common.context import context

# TypeVar para preservar el tipo específico de la clase
T = TypeVar('T')


class ProviderType(Enum):
    SINGLETON = "singleton"
    FACTORY = "factory"
    RESOURCE = "resource"
    OBJECT = "object"
    LIST = "list"


def get_component_key(cls: Type) -> str:
    """
    Genera una clave única para el componente basada en el tipo.
    
    Args:
        cls: El tipo/clase para el cual generar la clave
        
    Returns:
        Una clave única como string
        
    Raises:
        ValueError: Si el tipo List no tiene argumentos
    """
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


# Overloads para diferentes casos de uso
@overload
def component(
    _cls: Type[T],
) -> Type[T]: 
    """Registro manual directo: component(MyClass)"""
    ...

@overload
def component(
    _cls: None = None,
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
    value: Optional[object] = None,
) -> Callable[[Type[T]], Type[T]]: 
    """Decorador con parámetros: @component(provider_type=...)"""
    ...

@overload
def component(
    _cls: Type[T],
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
    value: Optional[object] = None,
) -> Type[T]: 
    """Registro manual con parámetros: component(MyClass, provider_type=...)"""
    ...


def component(
    _cls: Optional[Type[T]] = None,
    *,
    provider_type: ProviderType = ProviderType.SINGLETON,
    factory: Optional[Callable] = None,
    value: Optional[object] = None,
) -> Union[Type[T], Callable[[Type[T]], Type[T]]]:
    """
    Decorador/función dual para registrar componentes en el IOC.
    
    Uso como decorador:
        @component
        class MyService: 
            pass
        
        @component(provider_type=ProviderType.FACTORY)
        class MyFactory: 
            pass
    
    Uso como función de registro manual:
        component(MyService)  # Registro directo
        component(List[MyService], provider_type=ProviderType.LIST)  # Para listas
        component(AppContainer, provider_type=ProviderType.OBJECT, value=container)  # Para instancias
        component(provider_type=ProviderType.OBJECT)  # Para Tipos
        
    Args:
        _cls: La clase a registrar (None cuando se usa como decorador con parámetros)
        provider_type: Tipo de proveedor para el componente
        factory: Factory function opcional para crear instancias
        value: Valor pre-creado para componentes OBJECT
        
    Returns:
        La clase sin modificar o un decorador que preserva el tipo
        
    Raises:
        ValueError: En caso de configuración inválida o componente duplicado
    """
    component_registry = context.component_registry
    
    def register_component(target_cls: Type[T]) -> Type[T]:
        """
        Registra un componente en el registry con validaciones.
        
        Args:
            target_cls: La clase a registrar
            
        Returns:
            La misma clase sin modificaciones
            
        Raises:
            ValueError: Si hay errores de validación o duplicados
        """
        key = get_component_key(target_cls)
        
        # Verificar duplicados
        if key in component_registry:
            raise ValueError(f"Duplicated component: {key}")

        # Validaciones de consistencia
        if (provider_type in (ProviderType.SINGLETON, ProviderType.FACTORY) 
            and factory is not None and value is not None):
            raise ValueError(
                f"'factory' y 'value' no pueden usarse juntos para {key}"
            )     
            
        if (provider_type in (ProviderType.SINGLETON, ProviderType.FACTORY) 
            and value is not None):
            raise ValueError(
                f"'value' no es válido para provider_type={provider_type.value} en {key}"
            )
        
        if (provider_type == ProviderType.LIST 
            and (factory is not None or value is not None)):
            raise ValueError(
                f"'factory' y 'value' no son válidos para provider_type=LIST en {key}"
            )

        # Registro del componente
        component_registry[key] = {
            "cls": factory if factory is not None else target_cls,
            "provider_type": provider_type,
            "provider": None,
            "value": value if provider_type == ProviderType.OBJECT and value else target_cls,
        }
        
        # ¡IMPORTANTE! Devolver la clase original sin modificar
        return target_cls

    # Caso 1: Uso como registro manual directo (component(MyClass))
    if _cls is not None:
        return register_component(_cls)
    
    # Caso 2: Uso como decorador con parámetros (@component(...))
    return register_component