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
    get_origin,
    get_args,
)
from common.mapper import Mapper
from common.ioc import inject, deps
from common.mediator import Mediator

T = TypeVar("T")


class Delegate(Generic[T]):
    def __init__(self, name: Optional[str] = None):
        self.name = name


def invoke(name: Optional[str] = None) -> Any:
    return Delegate(name)


@runtime_checkable
class RepositoryProtocol(Protocol, Generic[T]):
    async def create(self, document: T, transaction: Any = None) -> None: ...
    async def get(self, id: UUID, message: str = None) -> T: ...
    async def update(self, document: T, transaction: Any = None) -> None: ...
    async def delete(self, doc: T, transaction: Any = None) -> None: ...
    async def find_by_field(
        self, field: str, value: Any, limit: Optional[int] = None, transaction: Any = None
    ) -> list[T]: ...


class RepoMeta(type):
    """Metaclase que genera automáticamente métodos asíncronos para delegados."""

    # Operaciones que requieren mapeo de entrada
    INPUT_MAPPING_OPERATIONS = {"create", "update", "delete"}
    # Operaciones que requieren mapeo de salida
    OUTPUT_MAPPING_OPERATIONS = {"get"}
    # Operaciones que requieren domain events
    DOMAIN_EVENT_OPERATIONS = {"create", "update"}

    def __new__(cls, name, bases, dct):
        delegate_attrs = cls._extract_delegate_attributes(dct)
        cls._generate_delegate_methods(dct, delegate_attrs)
        return super().__new__(cls, name, bases, dct)

    @classmethod
    def _extract_delegate_attributes(cls, dct):
        """Extrae los atributos marcados con Delegate."""
        delegate_attrs = {}
        for attr_name, value in dct.items():
            if (
                hasattr(value, "name")
                and hasattr(value, "__class__")
                and value.__class__.__name__ == "Delegate"
            ):
                protected_name = value.name or attr_name
                delegate_attrs[attr_name] = protected_name
        return delegate_attrs

    @classmethod
    def _generate_delegate_methods(cls, dct, delegate_attrs):
        """Genera métodos asíncronos para cada delegado."""
        for attr_name, protected_name in delegate_attrs.items():
            if cls._method_already_defined(dct, attr_name):
                continue

            needs_input_map = protected_name in cls.INPUT_MAPPING_OPERATIONS
            needs_output_map = protected_name in cls.OUTPUT_MAPPING_OPERATIONS
            needs_domain_events = protected_name in cls.DOMAIN_EVENT_OPERATIONS

            # Generar método asíncrono
            dct[attr_name] = cls._create_async_method(
                attr_name, protected_name, needs_input_map, needs_output_map, needs_domain_events
            )

    @staticmethod
    def _method_already_defined(dct, attr_name):
        """Verifica si el método ya está definido manualmente."""
        return attr_name in dct and not (
            hasattr(dct[attr_name], "name")
            and hasattr(dct[attr_name], "__class__")
            and dct[attr_name].__class__.__name__ == "Delegate"
        )

    @staticmethod
    def _create_async_method(
        attr_name, protected_name, needs_input_map, needs_output_map, needs_domain_events
    ):
        """Crea un método asíncrono para el delegado."""

        async def async_method(self, *args, **kwargs):
            target = RepoMeta._get_target_method(self, protected_name)

            # Procesar domain events ANTES de persistir
            if needs_domain_events and args:
                entity = args[0]
                await RepoMeta._handle_domain_events_before(self, entity)

            # Aplicar mapeo de entrada
            args, kwargs = RepoMeta._apply_input_mapping(
                self, args, kwargs, needs_input_map
            )

            # Ejecutar método del repositorio
            result = await target(*args, **kwargs)

            # Limpiar domain events DESPUÉS de persistir exitosamente
            if needs_domain_events and args:
                RepoMeta._clear_domain_events(args[0])

            # Aplicar mapeo de salida
            if needs_output_map:
                if isinstance(result, list):
                    result = [self._mapper.map(item) for item in result]
                else:
                    result = self._mapper.map(result)

            return result

        return async_method

    @staticmethod
    async def _handle_domain_events_before(instance, entity):
        """Maneja los eventos de dominio antes de persistir."""
        if hasattr(entity, 'get_events') and callable(entity.get_events):
            events = entity.get_events()
            if events:
                for event in events:
                    await instance._mediator.notify(event)

    @staticmethod
    def _clear_domain_events(entity):
        """Limpia los eventos de dominio después de persistir."""
        if hasattr(entity, 'clear_events') and callable(entity.clear_events):
            entity.clear_events()

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
        elif kwargs:
            first_key = next(iter(kwargs))
            kwargs[first_key] = instance._mapper.map(kwargs[first_key])

        return tuple(args), kwargs


# Interfaces delegadas
class Add(Generic[T], metaclass=RepoMeta):
    create: Callable[[T], Awaitable[None]] = invoke()
    """create(entity: T) -> Awaitable[None]"""


class Get(Generic[T], metaclass=RepoMeta):
    get: Callable[[UUID, Optional[str]], Awaitable[T]] = invoke()
    """get(id: UUID, message: Optional[str] = None) -> Awaitable[T]"""


class Update(Generic[T], Get[T], metaclass=RepoMeta):
    update: Callable[[T], Awaitable[None]] = invoke()
    """update(entity: T) -> Awaitable[None]"""


class Remove(Generic[T], Get[T], metaclass=RepoMeta):
    delete: Callable[[T], Awaitable[None]] = invoke("delete")
    """delete(entity: T) -> Awaitable[None]"""


class AbstractRepository(Generic[T]):
    """Repositorio abstracto que maneja automáticamente inyección, mapeo y eventos de dominio."""

    def __init_subclass__(cls, **kwargs):
        """Captura automáticamente el tipo del repositorio concreto."""
        super().__init_subclass__(**kwargs)
        
        # Buscar el tipo del repositorio concreto desde AbstractRepository[RepoType]
        for base in cls.__orig_bases__:
            origin = get_origin(base)
            if origin is AbstractRepository:
                args = get_args(base)
                if args:
                    cls._concrete_repo_type = args[0]
                    break
        else:
            raise ValueError(
                f"No se pudo determinar el tipo de repositorio concreto para {cls.__name__}. "
                f"Asegúrate de declarar la clase como: class {cls.__name__}(AbstractRepository[TuRepositorio], ...)"
            )

    @inject
    def __init__(
        self,
        repo:RepositoryProtocol,
        mapper: Mapper = deps(Mapper),
        mediator: Mediator = deps(Mediator),
    ):
        

        

        if not isinstance(mapper, Mapper):
            raise TypeError(f"{mapper!r} is not a Mapper")

        if not isinstance(mediator, Mediator):
            raise TypeError(f"{mediator!r} is not a Mediator")

        self._mapper = mapper
        self._mediator = mediator        
        self._repo = self.__class__._concrete_repo_type


# Composición de interfaces - Repositorio completo
class Repository(Generic[T], Add[T], Update[T], Remove[T], metaclass=RepoMeta):
    """Repositorio completo con todas las operaciones CRUD."""
    pass