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


class RepoMeta(type):
    def __new__(cls, name, bases, dct):
        delegate_attrs = {}

        # Detecta atributos que son Delegate
        for attr_name, value in dct.items():
            if isinstance(value, Delegate):
                protected = value.name or attr_name
                delegate_attrs[attr_name] = protected

        # Para cada atributo delegado, genera método si no está sobreescrito
        for attr_name, protected in delegate_attrs.items():
            if attr_name in dct and not isinstance(dct[attr_name], Delegate):
                continue  # Ya definido explícitamente en la clase (no es Delegate)

            def make_method(attr_name=attr_name, protected=protected):
                def sync_method(self, *args, **kwargs):
                    if not hasattr(self, "_repo"):
                        raise AttributeError(
                            f"'{type(self).__name__}' object has no attribute '_repo'"
                        )

                    target = getattr(self._repo, protected, None)
                    if not callable(target):
                        raise AttributeError(
                            f"'{type(self._repo).__name__}' object has no method '{protected}'"
                        )

                    if inspect.iscoroutinefunction(target):
                        raise RuntimeError(
                            f"Cannot call async method '{protected}' from sync context. "
                            f"Use 'await obj.{attr_name}_async(...)' instead."
                        )

                    return target(*args, **kwargs)

                return sync_method

            # Crear ambas versiones del método
            dct[attr_name] = make_method()  # versión sync

            # Crear versión async con sufijo '_async'
            def make_async_method(attr_name=attr_name, protected=protected):
                async def async_method(self, *args, **kwargs):
                    if not hasattr(self, "_repo"):
                        raise AttributeError(
                            f"'{type(self).__name__}' object has no attribute '_repo'"
                        )

                    target = getattr(self._repo, protected, None)
                    if not callable(target):
                        raise AttributeError(
                            f"'{type(self._repo).__name__}' object has no method '{protected}'"
                        )

                    if inspect.iscoroutinefunction(target):
                        return await target(*args, **kwargs)
                    else:
                        return target(*args, **kwargs)

                return async_method

            dct[f"{attr_name}_async"] = make_async_method()

        return super().__new__(cls, name, bases, dct)


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
    def __init__(self, repo: RepositoryProtocol):
        if not isinstance(repo, RepositoryProtocol):
            raise TypeError(f"{repo!r} does not implement RepositoryProtocol")
        self._repo = repo


# Composición de interfaces
class IRepo(Generic[T], Add[T], Update[T], Remove[T], metaclass=RepoMeta):
    pass
