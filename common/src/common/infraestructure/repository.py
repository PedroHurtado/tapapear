from uuid import UUID
from typing import (
    TypeVar,
    Generic,
    Optional,
    runtime_checkable,
    Protocol,
    Callable,
    Awaitable,
    get_origin,
    get_args,
)

from common.mapper import Mapper
from common.ioc import inject, deps, container
from common.mediator import EventBus

T = TypeVar("T")


class Delegate(Generic[T]):
    """Marker for a delegated repository operation."""

    def __init__(self, name: Optional[str] = None):
        self.name = name


def invoke(name: Optional[str] = None) -> Delegate:
    """Convenience factory returning a Delegate marker."""
    return Delegate(name)


@runtime_checkable
class RepositoryProtocol(Protocol, Generic[T]):
    """Domain-facing repository protocol (no infrastructure transaction parameter)."""

    async def create(self, document: T) -> None: ...
    async def get(self, id: UUID, message: Optional[str] = None) -> T: ...
    async def update(self, document: T) -> None: ...
    async def delete(self, doc: T) -> None: ...
    async def find_by_field(
        self, field: str, value: object, limit: Optional[int] = None
    ) -> list[T]: ...


class RepoMeta(type):
    """
    Metaclass that generates asynchronous methods for Delegate-marked attributes.

    Conventions:
    - Input mapping is applied only to the first positional argument (the entity).
    - Domain events are notified AFTER a successful persistence operation.
    - Delegate detection uses isinstance().
    """

    INPUT_MAPPING_OPERATIONS = {"create", "update", "delete"}
    OUTPUT_MAPPING_OPERATIONS = {"get"}
    DOMAIN_EVENT_OPERATIONS = {"create", "update"}

    def __new__(cls, name, bases, dct):
        delegate_attrs = cls._extract_delegate_attributes(dct)
        cls._generate_delegate_methods(dct, delegate_attrs)
        return super().__new__(cls, name, bases, dct)

    @classmethod
    def _extract_delegate_attributes(cls, dct):
        """Extract attributes that are marked with Delegate markers."""
        delegate_attrs: dict[str, str] = {}
        for attr_name, value in dct.items():
            if isinstance(value, Delegate):
                protected_name = value.name or attr_name
                delegate_attrs[attr_name] = protected_name
        return delegate_attrs

    @classmethod
    def _generate_delegate_methods(cls, dct, delegate_attrs):
        """Generate async methods for each delegate attribute."""
        for attr_name, protected_name in delegate_attrs.items():
            if cls._method_already_defined(dct, attr_name):
                continue

            needs_input_map = protected_name in cls.INPUT_MAPPING_OPERATIONS
            needs_output_map = protected_name in cls.OUTPUT_MAPPING_OPERATIONS
            needs_domain_events = protected_name in cls.DOMAIN_EVENT_OPERATIONS

            dct[attr_name] = cls._create_async_method(
                attr_name,
                protected_name,
                needs_input_map,
                needs_output_map,
                needs_domain_events,
            )

    @staticmethod
    def _method_already_defined(dct, attr_name):
        """Return True if method is defined manually (not a Delegate marker)."""
        if attr_name not in dct:
            return False
        return not isinstance(dct[attr_name], Delegate)

    @staticmethod
    def _create_async_method(attr_name, protected_name, needs_input_map, needs_output_map, needs_domain_events):
        """Create the asynchronous wrapper method for the delegate."""

        async def async_method(self, *args, **kwargs):
            target = RepoMeta._get_target_method(self, protected_name)

            # Validate and apply input mapping for operations that require it.
            args, kwargs = RepoMeta._apply_input_mapping(self, args, kwargs, needs_input_map)

            # Execute repository method (infrastructure concrete)
            result = await target(*args, **kwargs)

            # After successful persist, notify domain events if required.
            if needs_domain_events and args:
                await RepoMeta._handle_domain_events_after(self, args[0])
                RepoMeta._clear_domain_events(args[0])

            # Apply output mapping
            if needs_output_map and result is not None:
                if isinstance(result, list):
                    result = [self._mapper.map(item) for item in result]
                else:
                    result = self._mapper.map(result)

            return result

        return async_method

    @staticmethod
    async def _handle_domain_events_after(instance, entity):
        """Notify domain events after successful persistence."""
        if hasattr(entity, "get_events") and callable(entity.get_events):
            events = entity.get_events()
            if events:
                # If notification fails, the exception will propagate.
                for event in events:
                    await instance._event_bus.notify(event)

    @staticmethod
    def _clear_domain_events(entity):
        """Clear domain events from the entity after they have been notified."""
        if hasattr(entity, "clear_events") and callable(entity.clear_events):
            entity.clear_events()

    @staticmethod
    def _get_target_method(instance, protected_name):
        """Retrieve and validate the target method from the concrete repository instance."""
        if not hasattr(instance, "_repo") or not hasattr(instance, "_mapper"):
            raise AttributeError(f"{type(instance).__name__} is missing _repo or _mapper attributes")

        target = getattr(instance._repo, protected_name, None)
        if not callable(target):
            raise AttributeError(f"'{protected_name}' is not callable on underlying repository")

        return target

    @staticmethod
    def _apply_input_mapping(instance, args, kwargs, needs_input_map):
        """
        Apply input mapping to the first positional argument (the entity) when required.
        Raises a clear error if the operation expects an entity but none is provided.
        """
        if not needs_input_map:
            return args, kwargs

        args = list(args)

        if not args:
            raise ValueError("expected entity as first positional argument for this operation")

        args[0] = instance._mapper.map(args[0])
        return tuple(args), kwargs


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


class Repository(Generic[T], Add[T], Update[T], Remove[T], metaclass=RepoMeta):
    """Full repository composed of add/get/update/delete operations."""
    pass

class AbstractRepository(Generic[T]):
    """
    Abstract repository base that handles injection, mapper and mediator wiring.

    Subclasses must declare their concrete infrastructure repository type as:
        class MyRepo(AbstractRepository[ConcreteInfraRepo], ...):
            ...
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Try to find the concrete repository type from generic base parameters.
        concrete_type = None

        # Primary attempt: scan __orig_bases__ of the immediate class
        for base in getattr(cls, "__orig_bases__", ()):
            origin = get_origin(base)
            if origin is AbstractRepository:
                args = get_args(base)
                if args:
                    concrete_type = args[0]
                    break

        # Fallback: inspect MRO origins in case of complex inheritance
        if concrete_type is None:
            for base in cls.__mro__:
                for orig in getattr(base, "__orig_bases__", ()):
                    origin = get_origin(orig)
                    if origin is AbstractRepository:
                        args = get_args(orig)
                        if args:
                            concrete_type = args[0]
                            break
                if concrete_type is not None:
                    break

        if concrete_type is None:
            raise ValueError(
                f"Could not determine concrete repository type for {cls.__name__}. "
                f"Declare the class as: class {cls.__name__}(AbstractRepository[YourConcreteRepo], ...)"
            )

        cls.__concrete_repo_type = concrete_type

    @inject
    def __init__(
        self,
        mapper: Mapper = deps(Mapper),
        event_bus: EventBus = deps(EventBus),
    ):
        if not isinstance(mapper, Mapper):
            raise TypeError(f"{mapper!r} is not a Mapper")

        if not isinstance(event_bus, EventBus):
            raise TypeError(f"{event_bus} is not a EventBus")

        self._mapper = mapper
        self._event_bus = event_bus

    @property
    def _repo(self):
        if not hasattr(self, "_cached_repo"):
            self._cached_repo = container.get(self.__class__.__concrete_repo_type)
        return self._cached_repo



