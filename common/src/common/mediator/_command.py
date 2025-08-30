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
from pydantic import BaseModel, Field
from common.openapi import FeatureModel
from common.ioc import component, ProviderType
from common.context import context, Context
from common.domain.events import DomainEvent
from abc import ABC, abstractmethod, ABCMeta
import asyncio


class Command(FeatureModel): 
    pass


class Notification(DomainEvent): 
    pass


T = TypeVar("T", bound=Command)
N = TypeVar("N", bound=Notification)


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
            notification_type = mcs._extract_notification_type(cls)
            if notification_type:
                mcs._register_notification_handler(cls, notification_type)

        return cls

    @staticmethod
    def _extract_notification_type(cls) -> Optional[Type[Notification]]:
        if hasattr(cls, "__orig_bases__"):
            for base in cls.__orig_bases__:
                args = get_args(base)
                if args:
                    for arg in args:
                        if isinstance(arg, type) and issubclass(arg, Notification):
                            return arg
        return None

    @staticmethod
    def _register_notification_handler(handler_class: Type, notification_type: Type[Notification]):
        if notification_type not in context.notifications:
            context.notifications[notification_type] = []
        
        if handler_class not in context.notifications[notification_type]:
            context.notifications[notification_type].append(handler_class)


class CommandHadler(Generic[T], metaclass=CommandHanlderMeta):
    @abstractmethod
    async def handler(self, command: T) -> Any:
        pass


class NotificationHandler(Generic[N], metaclass=NotificationHandlerMeta):
    @abstractmethod
    async def handler(self, notification: N) -> None:
        pass


class PipelineContext:
    def __init__(self, message: Union[Command, Notification]):
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
        self, pipeline_context: PipelineContext, next_handler: Callable[[], Awaitable[None]]
    ) -> None:
        pass


def pipelines(
    *pipeline_classes: Type[Union["CommandPipeLine", "NotificationPipeLine"]],
) -> Callable[[Type[T]], Type[T]]:
    """
    Decorador para asignar pipelines específicos a una clase.

    Args:
        *pipeline_classes: Clases de pipeline a asignar

    Returns:
        Un decorador que asigna __pipelines__ con la lista de pipelines especificados
    """

    def decorator(cls: Type[T]) -> Type[T]:
        setattr(cls, "__pipelines__", list(pipeline_classes))
        return cls

    return decorator


@overload
def ignore_pipelines() -> Callable[[Type[T]], Type[T]]:
    """Decorador con paréntesis: @ignore_pipelines() -> __pipelines__ = []"""
    ...


@overload
def ignore_pipelines(cls: Type[T]) -> Type[T]:
    """Decorador directo: @ignore_pipelines -> __pipelines__ = []"""
    ...


def ignore_pipelines(cls: Type[T] = None) -> Type[T] | Callable[[Type[T]], Type[T]]:
    """
    Decorador para desactivar la ejecución de pipelines en una clase.

    Returns:
        La clase decorada con __pipelines__ = [], o un decorador que lo hace
    """

    def apply_ignore(target_cls: Type[T]) -> Type[T]:
        setattr(target_cls, "__pipelines__", [])
        return target_cls

    if cls is None:
        # Caso: @ignore_pipelines()
        return apply_ignore
    else:
        # Caso: @ignore_pipelines
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
    def __init__(
        self,
        handlers_data: List[Dict[str, Any]]
    ):
        self.handlers_data = handlers_data


@component
class Mediator:
    def __init__(
        self,
        commands_handlers: List[CommandHadler],
        commands_pipelines: List[CommandPipeLine],
        notifications_handlers: List[NotificationHandler],
        notification_pipelines: List[NotificationPipeLine],
        context: Context,
    ):
        self._commands_handlers = commands_handlers
        self._commands_pipelines = commands_pipelines        
        self._notifications_handlers = notifications_handlers
        self._notification_pipelines = notification_pipelines
        self._context = context
        self._handler_cache: Dict[Type[Command], CacheEntry] = {}
        self._notification_cache: Dict[Type[Notification], NotificationCacheEntry] = {}

    async def notify(self, notification: Notification) -> None:
        notification_type = type(notification)
        
        if notification_type not in self._notification_cache:
            self._build_notification_cache_entry(notification_type)
        
        cache_entry = self._notification_cache[notification_type]
        
        # Ejecutar todos los handlers en paralelo
        tasks = []
        for handler_data in cache_entry.handlers_data:
            pipeline_context = PipelineContext(notification)
            chain = handler_data['chain_factory'](pipeline_context)
            tasks.append(chain())
        
        if tasks:
            await asyncio.gather(*tasks)

    async def send(self, command: Command):
        command_type = type(command)

        if command_type not in self._handler_cache:
            self._build_cache_entry(command_type)

        cache_entry = self._handler_cache[command_type]
        pipeline_context = PipelineContext(command)
        chain = cache_entry.chain_factory(pipeline_context)
        return await chain()

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

    def _build_notification_cache_entry(self, notification_type: Type[Notification]):
        handler_types = self._context.notifications.get(notification_type, [])
        if not handler_types:
            # Sin handlers registrados, crear entrada vacía
            self._notification_cache[notification_type] = NotificationCacheEntry([])
            return

        handlers_data = []
        for handler_type in handler_types:
            handler = self._find_notification_handler(handler_type)
            pipelines = self._resolve_notification_pipelines(handler)
            chain_factory = self._create_notification_chain_factory(handler, pipelines)
            
            handlers_data.append({
                'handler': handler,
                'pipelines': pipelines,
                'chain_factory': chain_factory
            })

        self._notification_cache[notification_type] = NotificationCacheEntry(handlers_data)

    def _find_command_handler(self, service_type: Type) -> CommandHadler:
        service = next(
            (cmd for cmd in self._commands_handlers if type(cmd) == service_type), None
        )
        if service is None:
            raise ValueError(f"No se encontró instancia del handler {service_type}")
        return service

    def _find_notification_handler(self, handler_type: Type) -> NotificationHandler:
        handler = next(
            (h for h in self._notifications_handlers if type(h) == handler_type), None
        )
        if handler is None:
            raise ValueError(f"No se encontró instancia del notification handler {handler_type}")
        return handler

    def _resolve_command_pipelines(self, handler: CommandHadler) -> List[CommandPipeLine]:
        handler_class = type(handler)

        if hasattr(handler_class, "__pipelines__"):
            pipeline_classes = getattr(handler_class, "__pipelines__")
            if pipeline_classes:
                # Mantener el orden de declaración del decorador
                pipelines = []
                for pipeline_class in pipeline_classes:
                    pipeline_instance = next(
                        (p for p in self._commands_pipelines if type(p) == pipeline_class), None
                    )
                    if pipeline_instance:
                        pipelines.append(pipeline_instance)
            else:
                pipelines = []
        else:
            # Solo ordenar cuando no hay decorador (todos los pipelines)
            pipelines = list(self._commands_pipelines)
            pipelines.sort(key=lambda p: type(p).order)

        return pipelines

    def _resolve_notification_pipelines(self, handler: NotificationHandler) -> List[NotificationPipeLine]:
        handler_class = type(handler)

        if hasattr(handler_class, "__pipelines__"):
            pipeline_classes = getattr(handler_class, "__pipelines__")
            if pipeline_classes:
                # Mantener el orden de declaración del decorador
                pipelines = []
                for pipeline_class in pipeline_classes:
                    pipeline_instance = next(
                        (p for p in self._notification_pipelines if type(p) == pipeline_class), None
                    )
                    if pipeline_instance:
                        pipelines.append(pipeline_instance)
            else:
                pipelines = []
        else:
            # Solo ordenar cuando no hay decorador (todos los pipelines)
            pipelines = list(self._notification_pipelines)
            pipelines.sort(key=lambda p: type(p).order)

        return pipelines

    def _create_command_chain_factory(
        self, handler: CommandHadler, pipes: List[CommandPipeLine]
    ):
        def chain_factory(ctx: PipelineContext):
            async def service_handler():
                if ctx.cancelled:
                    return None
                return await handler.handler(ctx.message)

            next_handler = service_handler

            for pipeline in reversed(pipes):
                def create_pipeline_handler(pipe, next_h):
                    async def pipeline_handler():
                        if ctx.cancelled:
                            return None
                        return await pipe.handler(ctx, next_h)
                    return pipeline_handler

                next_handler = create_pipeline_handler(pipeline, next_handler)

            return next_handler
        return chain_factory

    def _create_notification_chain_factory(
        self, handler: NotificationHandler, pipes: List[NotificationPipeLine]
    ):
        def chain_factory(ctx: PipelineContext):
            async def service_handler():
                if ctx.cancelled:
                    return
                await handler.handler(ctx.message)

            next_handler = service_handler

            for pipeline in reversed(pipes):
                def create_pipeline_handler(pipe, next_h):
                    async def pipeline_handler():
                        if ctx.cancelled:
                            return
                        await pipe.handler(ctx, next_h)
                    return pipeline_handler

                next_handler = create_pipeline_handler(pipeline, next_handler)

            return next_handler
        return chain_factory

    def dispose(self):
        self._handler_cache.clear()
        self._notification_cache.clear()
        self._commands_pipelines.clear()
        self._commands_handlers.clear()        
        self._notification_pipelines.clear()
        self._notifications_handlers.clear()


component(List[CommandPipeLine], provider_type=ProviderType.LIST)
component(List[CommandHadler], provider_type=ProviderType.LIST)
component(List[NotificationPipeLine], provider_type=ProviderType.LIST)
component(List[NotificationHandler], provider_type=ProviderType.LIST)

component(Context, provider_type=ProviderType.OBJECT, value=context)