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
    cast,
    overload,
    TYPE_CHECKING,
    Union,
)
from common.openapi import FeatureModel
from common.ioc import component, ProviderType, AppContainer
from common.context import context
from abc import ABC, abstractmethod, ABCMeta

import inspect


class Command(FeatureModel): ...


T = TypeVar("T", bound=Command)


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


class CommandHadler(Generic[T], metaclass=CommandHanlderMeta):
    @abstractmethod
    def handler(self, command: T):
        pass


class PipelineContext:
    def __init__(self, command: Command):
        self.command = command
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


class PipeLine(ABC):
    @abstractmethod
    def handler(
        self, pipeline_context: PipelineContext, next_handler: Callable[[], Any]
    ) -> Any:
        pass


component(List[PipeLine], provider_type=ProviderType.LIST)


if TYPE_CHECKING:
    from ._command import PipeLine  # Ajusta la importación según tu estructura


@overload
def pipelines() -> Callable[[Type[T]], Type[T]]:
    """Decorador sin argumentos: @pipelines() -> __pipelines__ = []"""
    ...


@overload
def pipelines(*pipeline_classes: Type["PipeLine"]) -> Callable[[Type[T]], Type[T]]:
    """Decorador con argumentos: @pipelines(A, B, ...) -> __pipelines__ = [A, B, ...]"""
    ...


@overload
def pipelines(cls: Type[T]) -> Type[T]:
    """Decorador directo sin paréntesis: @pipelines -> __pipelines__ = []"""
    ...


def pipelines(
    *pipeline_classes: Union[Type["PipeLine"], Type[T]]
) -> Union[Type[T], Callable[[Type[T]], Type[T]]]:
    """
    Decorador para asignar pipelines a una clase.

    Usos:
        @pipelines            -> __pipelines__ = []  (anula todos)
        @pipelines()          -> __pipelines__ = []  (anula todos)
        @pipelines(A, B, ...) -> __pipelines__ = [A, B, ...] (solo esos)

    Args:
        *pipeline_classes: Clases de pipeline a asignar

    Returns:
        La clase decorada con __pipelines__ asignado, o un decorador que lo hace

    Examples:
        @pipelines
        class MyHandler:
            def process(self): ...

        @pipelines(ValidationPipeline, LoggingPipeline)
        class MyHandler:
            def process(self): ...
    """

    def apply_pipelines(
        cls: Type[T], pipelines_list: list[Type["PipeLine"]]
    ) -> Type[T]:
        """
        Aplica la lista de pipelines a la clase y preserva su tipo.

        Args:
            cls: La clase a decorar
            pipelines_list: Lista de pipelines a asignar

        Returns:
            La misma clase con __pipelines__ asignado
        """
        setattr(cls, "__pipelines__", pipelines_list)
        return cls

    # Caso 1: @pipelines sin paréntesis -> Python pasa la clase decorada aquí
    if len(pipeline_classes) == 1 and inspect.isclass(pipeline_classes[0]):
        candidate = pipeline_classes[0]

        # Si candidate parece una Pipeline (tiene 'handler'), entonces NO es la clase
        # decorada sino un argumento del decorador (ej. @pipelines(A)), así que
        # devolvemos un decorator factory que usará esa clase pipeline.
        if hasattr(candidate, "handler"):

            def decorator_with_pipeline(cls: Type[T]) -> Type[T]:
                return apply_pipelines(cls, [candidate])  # type: ignore[arg-type]

            return decorator_with_pipeline

        # Si no tiene 'handler', lo tratamos como la clase decorada: @pipelines
        return apply_pipelines(candidate, [])  # type: ignore[arg-type]

    # Caso 2: @pipelines() (sin argumentos) o @pipelines(A, B, ...) (con argumentos)
    def decorator_factory(cls: Type[T]) -> Type[T]:
        return apply_pipelines(cls, list(pipeline_classes))  # type: ignore[arg-type]

    return decorator_factory


@component
class Mediator:
    def __init__(self, pipelines: List[PipeLine], container: AppContainer):
        if container is None:
            raise ValueError("container no puede ser None")

        self._pipelines = pipelines or []
        self._container = container
        self._context = context

    def send(self, command: Command):
        command_type = type(command)
        service_type = self._context.commands.get(command_type, None)

        if service_type is None:
            raise ValueError(f"{service_type} no tiene registrado un command handler")

        service: CommandHadler = self._container.get(service_type)

        if hasattr(command_type, "__pipelines__"):
            pipeline_classes: list[type[PipeLine]] = getattr(
                command_type, "__pipelines__"
            )
            # Si el decorador está pero vacío → no se ejecuta ninguno
            if pipeline_classes:
                pipelines = [p for p in self._pipelines if type(p) in pipeline_classes]
            else:
                pipelines = []
        else:
            # Sin decorador → todos
            pipelines = list(self._pipelines)

        pipelines.sort(key=lambda p: type(p).order)

        pipeline_context = PipelineContext(command)

        def create_chain():
            # El último handler es el service
            def service_handler():
                if pipeline_context.cancelled:
                    return None
                return service.handler(command)

            next_handler = service_handler

            for pipeline in reversed(pipelines):

                def create_pipeline_handler(pipe, next_h):
                    def pipeline_handler():
                        if pipeline_context.cancelled:
                            return None
                        return pipe.handler(pipeline_context, next_h)

                    return pipeline_handler

                next_handler = create_pipeline_handler(pipeline, next_handler)

            return next_handler

        chain = create_chain()
        result = chain()
        return result
