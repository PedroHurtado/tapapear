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

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes

from common.mapper import Mapper
from common.ioc import inject, deps, container
from common.mediator import EventBus

T = TypeVar("T")

# OpenTelemetry tracer instance
tracer = trace.get_tracer(__name__)


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
    DOMAIN_EVENT_OPERATIONS = {"create", "update", "delete"}

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
            # Create root span for the repository operation
            with tracer.start_as_current_span(
                f"infrastructure.repository.{protected_name}",
                kind=trace.SpanKind.INTERNAL
            ) as span:
                try:
                    # Set initial span attributes
                    RepoMeta._set_initial_span_attributes(
                        span, self, protected_name, args, needs_input_map, needs_output_map, needs_domain_events
                    )

                    target = RepoMeta._get_target_method(self, protected_name)

                    # Apply input mapping with tracing
                    args_doc, kwargs_doc = await RepoMeta._apply_input_mapping_with_trace(
                        self, args, kwargs, needs_input_map, span
                    )

                    # Execute repository method with tracing
                    result = await RepoMeta._execute_concrete_repo_with_trace(
                        target, args_doc, kwargs_doc, span, self, protected_name
                    )

                    # Handle domain events with tracing
                    if needs_domain_events and args:
                        await RepoMeta._handle_domain_events_with_trace(self, args[0], span)

                    # Apply output mapping with tracing
                    if needs_output_map and result is not None:
                        result = await RepoMeta._apply_output_mapping_with_trace(
                            self, result, span
                        )

                    # Mark span as successful
                    span.set_status(Status(StatusCode.OK))
                    span.set_attribute("repository.operation.success", True)
                    
                    return result

                except Exception as e:
                    # Handle any error that occurs during the operation
                    RepoMeta._handle_span_error(span, e, protected_name)
                    raise

        return async_method

    @staticmethod
    def _set_initial_span_attributes(span, instance, protected_name, args, needs_input_map, needs_output_map, needs_domain_events):
        """Set initial attributes for the repository operation span."""
        span.set_attribute("repository.operation", protected_name)
        span.set_attribute("repository.class", instance.__class__.__name__)
        span.set_attribute("repository.input_mapping_required", needs_input_map)
        span.set_attribute("repository.output_mapping_required", needs_output_map)
        span.set_attribute("repository.domain_events_enabled", needs_domain_events)
        
        # Try to get entity information from first argument
        if args and hasattr(args[0], '__class__'):
            span.set_attribute("repository.entity_type", args[0].__class__.__name__)
            if hasattr(args[0], 'id') and args[0].id:
                span.set_attribute("repository.entity_id", str(args[0].id))

        # Set concrete repository type
        if hasattr(instance, '__concrete_repo_type'):
            span.set_attribute("repository.concrete_type", instance.__concrete_repo_type.__name__)

    @staticmethod
    async def _apply_input_mapping_with_trace(instance, args, kwargs, needs_input_map, parent_span):
        """Apply input mapping with OpenTelemetry tracing."""
        if not needs_input_map:
            return args, kwargs

        with tracer.start_as_current_span(
            "infrastructure.repository.input_mapping",
            kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                args = list(args)

                if not args:
                    raise ValueError("expected entity as first positional argument for this operation")

                # Set mapping span attributes
                entity = args[0]
                span.set_attribute("mapping.direction", "domain_to_document")
                span.set_attribute("mapping.entity_type", entity.__class__.__name__)
                span.set_attribute("mapper.class", instance._mapper.__class__.__name__)
                
                if hasattr(entity, 'id') and entity.id:
                    span.set_attribute("mapping.entity_id", str(entity.id))

                # Perform mapping
                mapped_entity = instance._mapper.map(entity)
                args[0] = mapped_entity

                # Mark mapping as successful
                span.set_status(Status(StatusCode.OK))
                span.set_attribute("mapping.success", True)
                
                return tuple(args), kwargs

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, f"Input mapping failed: {str(e)}"))
                span.set_attribute("mapping.success", False)
                span.set_attribute("mapping.error", str(e))
                raise

    @staticmethod
    async def _execute_concrete_repo_with_trace(target, args, kwargs, parent_span, instance, protected_name):
        """Execute the concrete repository method with tracing."""
        with tracer.start_as_current_span(
            f"infrastructure.repository.concrete.{protected_name}",
            kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                # Set concrete repository span attributes
                span.set_attribute("repository.concrete.method", protected_name)
                span.set_attribute("repository.concrete.class", instance._repo.__class__.__name__)
                
                # Execute the concrete repository method
                result = await target(*args, **kwargs)
                
                # Mark execution as successful
                span.set_status(Status(StatusCode.OK))
                span.set_attribute("repository.concrete.success", True)
                
                return result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, f"Concrete repository execution failed: {str(e)}"))
                span.set_attribute("repository.concrete.success", False)
                span.set_attribute("repository.concrete.error", str(e))
                raise

    @staticmethod
    async def _handle_domain_events_with_trace(instance, entity, parent_span):
        """Handle domain events with OpenTelemetry tracing."""
        if not (hasattr(entity, "get_events") and callable(entity.get_events)):
            return

        events = entity.get_events()
        if not events:
            return

        with tracer.start_as_current_span(
            "infrastructure.repository.domain_events",
            kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                # Set domain events span attributes
                span.set_attribute("events.count", len(events))
                span.set_attribute("events.entity_type", entity.__class__.__name__)
                
                if hasattr(entity, 'id') and entity.id:
                    span.set_attribute("events.entity_id", str(entity.id))

                event_types = [event.__class__.__name__ for event in events]
                span.set_attribute("events.types", ",".join(event_types))

                # Notify each event with individual tracing
                for i, event in enumerate(events):
                    await RepoMeta._notify_single_event_with_trace(
                        instance._event_bus, event, i, span
                    )

                # Clear events after successful processing
                RepoMeta._clear_domain_events(entity)
                
                # Mark events processing as successful
                span.set_status(Status(StatusCode.OK))
                span.set_attribute("events.success", True)
                span.set_attribute("events.cleared", True)

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, f"Domain events processing failed: {str(e)}"))
                span.set_attribute("events.success", False)
                span.set_attribute("events.error", str(e))
                raise

    @staticmethod
    async def _notify_single_event_with_trace(event_bus, event, event_index, parent_span):
        """Notify a single domain event with tracing."""
        with tracer.start_as_current_span(
            f"infrastructure.repository.event_notification",
            kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                # Set event notification span attributes
                span.set_attribute("event.type", event.__class__.__name__)
                span.set_attribute("event.index", event_index)
                span.set_attribute("event_bus.class", event_bus.__class__.__name__)
                
                # Add event-specific attributes if available
                if hasattr(event, 'id'):
                    span.set_attribute("event.entity_id", str(event.id))
                
                # Notify the event
                await event_bus.notify(event)
                
                # Mark notification as successful
                span.set_status(Status(StatusCode.OK))

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, f"Event notification failed: {str(e)}"))
                span.set_attribute("event.notification.error", str(e))
                raise

    @staticmethod
    async def _apply_output_mapping_with_trace(instance, result, parent_span):
        """Apply output mapping with OpenTelemetry tracing."""
        with tracer.start_as_current_span(
            "infrastructure.repository.output_mapping",
            kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                is_collection = isinstance(result, list)
                span.set_attribute("mapping.direction", "document_to_domain")
                span.set_attribute("mapping.is_collection", is_collection)
                span.set_attribute("mapper.class", instance._mapper.__class__.__name__)
                
                if is_collection:
                    span.set_attribute("mapping.collection_size", len(result))
                    mapped_result = [instance._mapper.map(item) for item in result]
                    if result:  # Set entity type from first item
                        span.set_attribute("mapping.entity_type", result[0].__class__.__name__)
                else:
                    span.set_attribute("mapping.entity_type", result.__class__.__name__)
                    mapped_result = instance._mapper.map(result)
                    if hasattr(result, 'id') and result.id:
                        span.set_attribute("mapping.entity_id", str(result.id))

                # Mark mapping as successful
                span.set_status(Status(StatusCode.OK))
                span.set_attribute("mapping.success", True)
                
                return mapped_result

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, f"Output mapping failed: {str(e)}"))
                span.set_attribute("mapping.success", False)
                span.set_attribute("mapping.error", str(e))
                raise

    @staticmethod
    def _handle_span_error(span, exception, operation_name):
        """Handle errors in the main repository span."""
        span.set_status(Status(StatusCode.ERROR, f"Repository {operation_name} failed: {str(exception)}"))
        span.set_attribute("repository.operation.success", False)
        span.set_attribute("repository.operation.error", str(exception))
        span.set_attribute("repository.operation.error_type", exception.__class__.__name__)

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
        self._mapper = mapper
        self._event_bus = event_bus

    @property
    def _repo(self):
        if not hasattr(self, "_cached_repo"):
            self._cached_repo = container.get(self.__class__.__concrete_repo_type)
        return self._cached_repo