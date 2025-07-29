import inspect
import asyncio
from typing import (
    Callable,
    Protocol,
    Optional,
    Any,
    TypeVar,
    Generic,
    runtime_checkable,
    Awaitable,
)

T = TypeVar("T")


class Delegate(Generic[T]):
    def __init__(self, name: Optional[str] = None):
        self.name = name


def invoke(name: Optional[str] = None) -> Any:
    return Delegate(name)


@runtime_checkable
class RepositoryProtocol(Protocol):
    def _create(self, name: str) -> None: ...
    def _get(self, name: str) -> None: ...
    def _update(self, name: str) -> None: ...
    def _remove(self, name: str) -> None: ...


class RepoMeta(type):
    def __new__(cls, name, bases, dct):
        delegate_attrs = {}

        # Detecta atributos que son Delegate
        for attr_name, value in dct.items():
            if isinstance(value, Delegate):
                protected = value.name or f"_{attr_name}"
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
class Add(metaclass=RepoMeta):
    create: Callable[[str], None] = invoke()
    create_async: Callable[[str], Awaitable[None]] = invoke()


class Get(metaclass=RepoMeta):
    get: Callable[[str], None] = invoke()


class Update(Get, metaclass=RepoMeta):
    update: Callable[[str], None] = invoke()


class Remove(Get, metaclass=RepoMeta):
    remove: Callable[[str], None] = invoke()


# Esta clase NO debe tener metaclass, para que __init__ sea visible
class InjectsRepo:
    def __init__(self, repo: RepositoryProtocol):
        if not isinstance(repo, RepositoryProtocol):
            raise TypeError(f"{repo!r} does not implement RepositoryProtocol")
        self._repo = repo


# Composición de interfaces
class IRepo(Add, Update, Remove, metaclass=RepoMeta):
    pass


# Repo concreto
class BarRepo(InjectsRepo, IRepo):
    pass


# Implementación concreta (sync)
class RepoBase:
    def _create(self, name: str):
        print(f"[CREATE] {name}")

    def _get(self, name: str):
        print(f"[GET] {name}")

    def _update(self, name: str):
        print(f"[UPDATE] {name}")

    def _remove(self, name: str):
        print(f"[REMOVE] {name}")    
    

# Implementación concreta (async)
class AsyncRepoBase:
    async def _create(self, name: str):
        print(f"[ASYNC CREATE] {name}")

    async def _get(self, name: str):
        print(f"[ASYNC GET] {name}")

    async def _update(self, name: str):
        print(f"[ASYNC UPDATE] {name}")

    async def _remove(self, name: str):
        print(f"[ASYNC REMOVE] {name}")




# 🔍 Ejemplo de uso
if __name__ == "__main__":
    print("=== OPERACIONES SÍNCRONAS ===")
    barrepo = BarRepo(RepoBase())
    barrepo.create("Pedro")    
    barrepo.get("Pedro")
    barrepo.update("Pedro actualizado")
    barrepo.remove("Pedro borrado")    

    print("\n=== OPERACIONES ASÍNCRONAS ===")

    async def test_async():
        async_repo = BarRepo(AsyncRepoBase())
        await async_repo.create_async("Pedro Async")
        await async_repo.get_async("Pedro Async")
        await async_repo.update_async("Pedro Async actualizado")
        await async_repo.remove_async("Pedro Async borrado")
        

    asyncio.run(test_async())

    print("\n=== PROBANDO MEZCLA (ERROR ESPERADO) ===")
    mixed_repo = BarRepo(AsyncRepoBase())
    try:
        mixed_repo.create("Esto debería fallar")
    except RuntimeError as e:
        print(f"Error esperado: {e}")
