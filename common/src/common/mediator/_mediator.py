from typing import (
    TypeVar,
    Generic,
    List,
    Type,
    Optional,
    get_args,
    Dict,
    Any,
    Callable,
    overload,
    Awaitable,
    Union,
)
from pydantic import BaseModel
from common.openapi import FeatureModel
from common.ioc import component, ProviderType, inject, deps
from common.context import context, Context
from common.domain.events import DomainEvent
from abc import ABC, abstractmethod, ABCMeta
import asyncio
import uuid
from opentelemetry import trace


class Command(FeatureModel):
    pass


T = TypeVar("T", bound=Command)
N = TypeVar("N", bound=DomainEvent)


# Excepción para commands duplicados
class DuplicateCommandError(Exception):
    def __init__(
        self, command_type: Type[Command], existing_service: Type, new_service: Type
    ):
        super().__init__(
            f"Command {command_type.__name__} is already registered to {existing_service.__name__}. "
            f"Cannot register it to {new_service.__name__}."
        )


class CommandHanlderMeta(ABCMeta):
    """Metaclass que registra automáticamente los Services al definir la clase"""

    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace)

        if name != "CommandHadler" and bases:
            command_type = mcs._extract_command_type(cls)
            if command_type:
                mcs._register_service(cls, command_type)

        return cls

    @staticmethod
    def _extract_command_type(cls) -> Optional[Type[Command]]:
        if hasattr(cls, "__orig_bases__"):
            for base in cls.__orig_bases__:
                args = get_args(base)
                if args:
                    for arg in args:
                        if isinstance(arg, type) and issubclass(arg, Command):
                            return arg
        return None

    @staticmethod
    def _register_service(service_class: Type, command_type: Type[Command]):

        if command_type in context.commands:
            existing_service = context.commands[command_type]
            if existing_service != service_class:
                raise DuplicateCommandError(
                    command_type, existing_service, service_class
                )

        context.commands[command_type] = service_class


class NotificationHandlerMeta(ABCMeta):
    """Metaclass que registra automáticamente los NotificationHandlers al definir la clase"""

    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace)

        if name != "NotificationHandler" and bases:
            domain_event_type = mcs._extract_domain_event_type(cls)
            if domain_event_type:
                mcs._register_domain_event_handler(cls, domain_event_type)

        return cls

    @staticmethod
    def _extract_domain_event_type(cls) -> Optional[Type[DomainEvent]]:
        if hasattr(cls, "__orig_bases__"):
            for base in cls.__orig_bases__:
                args = get_args(base)
                if args:
                    for arg in args:
                        if isinstance(arg, type) and issubclass(arg, DomainEvent):
                            return arg
        return None

    @staticmethod
    def _register_domain_event_handler(
        handler_class: Type, domain_event_type: Type[DomainEvent]
    ):
        if domain_event_type not in context.notifications:
            context.notifications[domain_event_type] = []

        if handler_class not in context.notifications[domain_event_type]:
            context.notifications[domain_event_type].append(handler_class)


class CommandHadler(Generic[T], metaclass=CommandHanlderMeta):
    @abstractmethod
    async def handler(self, command: T) -> Any:
        pass


class NotificationHandler(Generic[N], metaclass=NotificationHandlerMeta):
    @abstractmethod
    async def handler(self, domain_event: N) -> None:
        pass


class PipelineContext:
    def __init__(self, message: Union[Command, DomainEvent]):
        self.message = message
        self.data: Dict[str, Any] = {}
        self.cancelled = False

    def cancel(self):
        """Cancela la ejecución del pipeline"""
        self.cancelled = True

    def set_data(self, key: str, value: Any):
        """Almacena datos para pipelines posteriores"""
        self.data[key] = value

    def get_data(self, key: str, default: Any = None):
        """Obtiene datos almacenados por pipelines anteriores"""
        return self.data.get(key, default)


def ordered(order: int):
    def decorator(cls):
        cls.order = order
        return cls

    return decorator


class CommandPipeLine(ABC):
    @abstractmethod
    async def handler(
        self, pipeline_context: PipelineContext, next_handler: Callable[[], Any]
    ) -> Any:
        pass


class NotificationPipeLine(ABC):
    @abstractmethod
    async def handler(
        self,
        pipeline_context: PipelineContext,
        next_handler: Callable[[], Awaitable[None]],
    ) -> None:
        pass


def pipelines(
    *pipeline_classes: Type[Union["CommandPipeLine", "NotificationPipeLine"]],
) -> Callable[[Type[T]], Type[T]]:
    """
    Decorador para asignar pipelines específicos a una clase.
    """

    def decorator(cls: Type[T]) -> Type[T]:
        setattr(cls, "__pipelines__", list(pipeline_classes))
        return cls

    return decorator


@overload
def ignore_pipelines() -> Callable[[Type[T]], Type[T]]: ...
@overload
def ignore_pipelines(cls: Type[T]) -> Type[T]: ...


def ignore_pipelines(cls: Type[T] = None) -> Type[T] | Callable[[Type[T]], Type[T]]:
    """Decorador para desactivar pipelines en una clase."""

    def apply_ignore(target_cls: Type[T]) -> Type[T]:
        setattr(target_cls, "__pipelines__", [])
        return target_cls

    if cls is None:
        return apply_ignore
    else:
        return apply_ignore(cls)


class CacheEntry:
    def __init__(
        self,
        command_handler: CommandHadler,
        pipelines: List[CommandPipeLine],
        chain_factory: Callable[[PipelineContext], Callable[[], Awaitable]],
    ):
        self.command_handler = command_handler
        self.pipelines = pipelines
        self.chain_factory = chain_factory


class NotificationCacheEntry:
    def __init__(self, handlers_data: List[Dict[str, Any]]):
        self.handlers_data = handlers_data


# ---------------- MEDIATOR (solo send) ----------------
@component
class Mediator:
    def __init__(
        self,
        commands_handlers: List[CommandHadler],
        commands_pipelines: List[CommandPipeLine],
        context: Context,
    ):
        self._commands_handlers = commands_handlers
        self._commands_pipelines = commands_pipelines
        self._context = context
        self._handler_cache: Dict[Type[Command], CacheEntry] = {}
        self._tracer = trace.get_tracer(__name__)

    async def send(self, command: Command):
        command_type = type(command)
        command_id = getattr(command, "id", str(uuid.uuid4()))

        with self._tracer.start_as_current_span("mediator.send") as span:
            try:
                span.set_attributes(
                    {
                        "mediator.operation": "send",
                        "mediator.command.type": command_type.__name__,
                        "mediator.command.id": str(command_id),
                    }
                )

                cache_hit = command_type in self._handler_cache
                span.set_attribute("mediator.cache.hit", cache_hit)

                if not cache_hit:
                    with self._tracer.start_as_current_span("mediator.cache_build"):
                        self._build_cache_entry(command_type)

                cache_entry = self._handler_cache[command_type]
                pipeline_context = PipelineContext(command)
                chain = cache_entry.chain_factory(pipeline_context)
                result = await chain()

                span.set_status(trace.Status(trace.StatusCode.OK))
                return result
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    def _build_cache_entry(self, command_type: Type[Command]):
        service_type = self._context.commands.get(command_type, None)
        if service_type is None:
            raise ValueError(f"{command_type} no tiene registrado un command handler")

        service = self._find_command_handler(service_type)
        pipelines = self._resolve_command_pipelines(service)
        chain_factory = self._create_command_chain_factory(service, pipelines)

        self._handler_cache[command_type] = CacheEntry(
            service, pipelines, chain_factory
        )

    def _find_command_handler(self, service_type: Type) -> CommandHadler:
        service = next(
            (cmd for cmd in self._commands_handlers if type(cmd) == service_type), None
        )
        if service is None:
            raise ValueError(f"No se encontró instancia del handler {service_type}")
        return service

    def _resolve_command_pipelines(
        self, handler: CommandHadler
    ) -> List[CommandPipeLine]:
        handler_class = type(handler)
        if hasattr(handler_class, "__pipelines__"):
            pipeline_classes = getattr(handler_class, "__pipelines__")
            pipelines = [
                next((p for p in self._commands_pipelines if type(p) == pc), None)
                for pc in pipeline_classes
            ]
            return [p for p in pipelines if p]
        else:
            pipelines = list(self._commands_pipelines)
            pipelines.sort(key=lambda p: type(p).order)
            return pipelines

    def _create_command_chain_factory(
        self, handler: CommandHadler, pipes: List[CommandPipeLine]
    ):
        def chain_factory(ctx: PipelineContext):
            async def service_handler():
                with self._tracer.start_as_current_span("handler.execute"):
                    return await handler.handler(ctx.message)

            next_handler = service_handler
            for position, pipeline in enumerate(reversed(pipes), 1):

                def create_pipeline_handler(pipe, next_h):
                    async def pipeline_handler():
                        with self._tracer.start_as_current_span("pipeline.execute"):
                            return await pipe.handler(ctx, next_h)

                    return pipeline_handler

                next_handler = create_pipeline_handler(pipeline, next_handler)
            return next_handler

        return chain_factory

    def dispose(self):
        self._handler_cache.clear()
        self._commands_pipelines.clear()
        self._commands_handlers.clear()


# ---------------- EVENT BUS (solo notify) ----------------
@component
class EventBus:
    def __init__(
        self,
        notification_pipelines: List[NotificationPipeLine],
        context: Context,
    ):

        self._notification_pipelines = notification_pipelines
        self._context = context
        self._notification_cache: Dict[Type[DomainEvent], NotificationCacheEntry] = {}
        self._tracer = trace.get_tracer(__name__)

    @inject
    async def notify(
        self,
        domain_event: DomainEvent,
        notifications_handlers: List[NotificationHandler] = deps(
            List[NotificationHandler]
        ),
    ) -> None:
        self._notifications_handlers = notifications_handlers

        domain_event_type = type(domain_event)
        domain_event_id = getattr(domain_event, "id", str(uuid.uuid4()))

        with self._tracer.start_as_current_span("eventbus.notify") as span:
            try:
                span.set_attributes(
                    {
                        "eventbus.operation": "notify",
                        "eventbus.domain_event.type": domain_event_type.__name__,
                        "eventbus.domain_event.id": str(domain_event_id),
                    }
                )

                cache_hit = domain_event_type in self._notification_cache
                span.set_attribute("eventbus.cache.hit", cache_hit)

                if not cache_hit:
                    with self._tracer.start_as_current_span("eventbus.cache_build"):
                        self._build_notification_cache_entry(domain_event_type)

                cache_entry = self._notification_cache[domain_event_type]
                handlers_count = len(cache_entry.handlers_data)
                span.set_attribute("eventbus.handlers.count", handlers_count)

                tasks = [
                    self._execute_handler_chain(i, h_data, domain_event)
                    for i, h_data in enumerate(cache_entry.handlers_data)
                ]

                if tasks:
                    await asyncio.gather(*tasks)

                span.set_status(trace.Status(trace.StatusCode.OK))
            except Exception as e:
                span.record_exception(e)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                raise

    async def _execute_handler_chain(
        self, idx: int, h_data: Dict[str, Any], domain_event: DomainEvent
    ):
        with self._tracer.start_as_current_span("eventbus.handler_chain"):
            handler = h_data["handler"]
            pipelines = h_data["pipelines"]
            pipeline_context = PipelineContext(domain_event)
            chain = h_data["chain_factory"](pipeline_context)
            await chain()

    def _build_notification_cache_entry(self, domain_event_type: Type[DomainEvent]):
        handler_types = self._context.notifications.get(domain_event_type, [])
        if not handler_types:
            self._notification_cache[domain_event_type] = NotificationCacheEntry([])
            return

        handlers_data = []
        for handler_type in handler_types:
            handler = self._find_notification_handler(handler_type)
            pipelines = self._resolve_notification_pipelines(handler)
            chain_factory = self._create_notification_chain_factory(handler, pipelines)
            handlers_data.append(
                {
                    "handler": handler,
                    "pipelines": pipelines,
                    "chain_factory": chain_factory,
                }
            )

        self._notification_cache[domain_event_type] = NotificationCacheEntry(
            handlers_data
        )

    def _find_notification_handler(self, handler_type: Type) -> NotificationHandler:
        handler = next(
            (h for h in self._notifications_handlers if type(h) == handler_type), None
        )
        if handler is None:
            raise ValueError(
                f"No se encontró instancia del notification handler {handler_type}"
            )
        return handler

    def _resolve_notification_pipelines(
        self, handler: NotificationHandler
    ) -> List[NotificationPipeLine]:
        handler_class = type(handler)
        if hasattr(handler_class, "__pipelines__"):
            pipeline_classes = getattr(handler_class, "__pipelines__")
            pipelines = [
                next((p for p in self._notification_pipelines if type(p) == pc), None)
                for pc in pipeline_classes
            ]
            return [p for p in pipelines if p]
        else:
            pipelines = list(self._notification_pipelines)
            pipelines.sort(key=lambda p: type(p).order)
            return pipelines

    def _create_notification_chain_factory(
        self, handler: NotificationHandler, pipes: List[NotificationPipeLine]
    ):
        def chain_factory(ctx: PipelineContext):
            async def service_handler():
                with self._tracer.start_as_current_span("domain_event_handler.execute"):
                    await handler.handler(ctx.message)

            next_handler = service_handler
            for pipeline in reversed(pipes):

                def create_pipeline_handler(pipe, next_h):
                    async def pipeline_handler():
                        with self._tracer.start_as_current_span(
                            "notification_pipeline.execute"
                        ):
                            await pipe.handler(ctx, next_h)

                    return pipeline_handler

                next_handler = create_pipeline_handler(pipeline, next_handler)
            return next_handler

        return chain_factory

    def dispose(self):
        self._notification_cache.clear()
        self._notification_pipelines.clear()
        self._notifications_handlers.clear()


# Providers para IoC
component(List[CommandPipeLine], provider_type=ProviderType.LIST)
component(List[CommandHadler], provider_type=ProviderType.LIST)
component(List[NotificationPipeLine], provider_type=ProviderType.LIST)
component(List[NotificationHandler], provider_type=ProviderType.LIST)
component(Context, provider_type=ProviderType.OBJECT, value=context)
