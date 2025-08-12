import inspect
from uuid import UUID
from typing import (
    TypeVar,
    Generic,
    Optional,
    Any,
    runtime_checkable,
    Protocol,
    Callable,
    Awaitable,
)
from automapper import Mapper

T = TypeVar("T")


class Delegate(Generic[T]):
    def __init__(self, name: Optional[str] = None):
        self.name = name


def invoke(name: Optional[str] = None) -> Any:
    return Delegate(name)


@runtime_checkable
class RepositoryProtocol(Protocol, Generic[T]):
    def create(self, entity: T) -> None: ...
    def get(self, id: UUID) -> T: ...
    def update(self, entity: T) -> None: ...
    def remove(self, entity: T) -> None: ...
    def find_by_field(
        self, field: str, value: Any, limit: Optional[int] = None
    ) -> list[T]:...


import inspect


class RepoMeta(type):
    """Metaclase que genera automáticamente métodos síncronos y asíncronos para delegados."""
    
    # Operaciones que requieren mapeo de entrada
    INPUT_MAPPING_OPERATIONS = {"create", "update", "remove"}
    # Operaciones que requieren mapeo de salida
    OUTPUT_MAPPING_OPERATIONS = {"get"}
    
    def __new__(cls, name, bases, dct):
        delegate_attrs = cls._extract_delegate_attributes(dct)
        cls._generate_delegate_methods(dct, delegate_attrs)
        return super().__new__(cls, name, bases, dct)
    
    @classmethod
    def _extract_delegate_attributes(cls, dct):
        """Extrae los atributos marcados con Delegate."""
        delegate_attrs = {}
        for attr_name, value in dct.items():
            if hasattr(value, 'name') and hasattr(value, '__class__') and value.__class__.__name__ == 'Delegate':
                protected_name = value.name or attr_name
                delegate_attrs[attr_name] = protected_name
        return delegate_attrs
    
    @classmethod
    def _generate_delegate_methods(cls, dct, delegate_attrs):
        """Genera métodos síncronos y asíncronos para cada delegado."""
        for attr_name, protected_name in delegate_attrs.items():
            if cls._method_already_defined(dct, attr_name):
                continue
            
            needs_input_map = protected_name in cls.INPUT_MAPPING_OPERATIONS
            needs_output_map = protected_name in cls.OUTPUT_MAPPING_OPERATIONS
            
            # Generar método síncrono
            dct[attr_name] = cls._create_sync_method(
                attr_name, protected_name, needs_input_map, needs_output_map
            )
            
            # Generar método asíncrono
            dct[f"{attr_name}_async"] = cls._create_async_method(
                attr_name, protected_name, needs_input_map, needs_output_map
            )
    
    @staticmethod
    def _method_already_defined(dct, attr_name):
        """Verifica si el método ya está definido manualmente."""
        return (attr_name in dct and 
                not (hasattr(dct[attr_name], 'name') and 
                     hasattr(dct[attr_name], '__class__') and 
                     dct[attr_name].__class__.__name__ == 'Delegate'))
    
    @staticmethod
    def _create_sync_method(attr_name, protected_name, needs_input_map, needs_output_map):
        """Crea un método síncrono para el delegado."""
        def sync_method(self, *args, **kwargs):
            target = RepoMeta._get_target_method(self, protected_name)
            
            if inspect.iscoroutinefunction(target):
                raise RuntimeError(
                    f"Cannot call async method '{protected_name}' from sync context. "
                    f"Use 'await obj.{attr_name}_async(...)' instead."
                )
            
            args, kwargs = RepoMeta._apply_input_mapping(
                self, args, kwargs, needs_input_map
            )
            
            result = target(*args, **kwargs)
            
            if needs_output_map:
                result = self._mapper.map(result)
            
            return result
        
        return sync_method
    
    @staticmethod
    def _create_async_method(attr_name, protected_name, needs_input_map, needs_output_map):
        """Crea un método asíncrono para el delegado."""
        async def async_method(self, *args, **kwargs):
            target = RepoMeta._get_target_method(self, protected_name)
            
            args, kwargs = RepoMeta._apply_input_mapping(
                self, args, kwargs, needs_input_map
            )
            
            # Ejecutar método (síncrono o asíncrono)
            if inspect.iscoroutinefunction(target):
                result = await target(*args, **kwargs)
            else:
                result = target(*args, **kwargs)
            
            if needs_output_map:
                result = self._mapper.map(result)
            
            return result
        
        return async_method
    
    @staticmethod
    def _get_target_method(instance, protected_name):
        """Obtiene y valida el método objetivo del repositorio."""
        if not hasattr(instance, "_repo") or not hasattr(instance, "_mapper"):
            raise AttributeError(
                f"{type(instance).__name__} missing _repo or _mapper attributes"
            )
        
        target = getattr(instance._repo, protected_name, None)
        if not callable(target):
            raise AttributeError(f"'{protected_name}' is not callable")
        
        return target
    
    @staticmethod
    def _apply_input_mapping(instance, args, kwargs, needs_input_map):
        """Aplica el mapeo de entrada si es necesario."""
        if not needs_input_map:
            return args, kwargs
        
        args = list(args)
        
        # Mapear primer argumento posicional si existe
        if args:
            args[0] = instance._mapper.map(args[0])
        # O mapear el primer argumento de palabra clave
        elif kwargs:
            first_key = next(iter(kwargs))
            kwargs[first_key] = instance._mapper.map(kwargs[first_key])
        
        return tuple(args), kwargs


# Interfaces delegadas


class Add(Generic[T], metaclass=RepoMeta):
    create: Callable[[T], None] = invoke()
    """create(entity: T) -> None"""

    create_async: Callable[[T], Awaitable[None]] = invoke()
    """create_async(entity: T) -> Awaitable[None]"""


class Get(Generic[T], metaclass=RepoMeta):
    get: Callable[[UUID, Optional[str]], T] = invoke()
    """get(id: UUID, message: Optional[str] = None) -> T"""

    get_async: Callable[[UUID, Optional[str]], Awaitable[T]] = invoke()
    """get_async(id: UUID, message: Optional[str] = None) -> Awaitable[T]"""


class Update(Generic[T], Get[T], metaclass=RepoMeta):
    update: Callable[[T], None] = invoke()
    """update(entity: T) -> None"""

    update_async: Callable[[T], Awaitable[None]] = invoke()
    """update_async(entity: T) -> Awaitable[None]"""


class Remove(Generic[T], Get[T], metaclass=RepoMeta):
    remove: Callable[[T], None] = invoke()
    """remove(entity: T) -> None"""

    remove_async: Callable[[T], Awaitable[None]] = invoke()
    """remove_async(entity: T) -> Awaitable[None]"""


# Esta clase NO debe tener metaclass, para que __init__ sea visible
class InjectsRepo:
    def __init__(self, repo: RepositoryProtocol, mapper:Mapper):
        #if not isinstance(repo, RepositoryProtocol):
        #    raise TypeError(f"{repo!r} does not implement RepositoryProtocol")
        
        if not isinstance(mapper, Mapper):
            raise TypeError(f"{mapper!r} is not a Mapper")
        self._repo = repo
        self._mapper = mapper


# Composición de interfaces
class Repository(Generic[T], Add[T], Update[T], Remove[T], metaclass=RepoMeta):
    pass
