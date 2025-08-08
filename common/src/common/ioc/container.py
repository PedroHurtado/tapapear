# container.py
import inspect
from dependency_injector import containers, providers

from common.ioc.component import ProviderType, component_registry, get_component_key


class AppContainer(containers.DynamicContainer):
    pass


container = AppContainer()


def build_container():
    # Primer pase: declarar el contenedor con claves vacías
    for key in component_registry:
        container.__dict__[key] = None

    # Segundo pase: construir providers con dependencias
    for key, meta in component_registry.items():
        cls = meta["cls"]
        provider_type = meta["provider_type"]

        sig = inspect.signature(cls.__init__)
        kwargs = {}
        for param in sig.parameters.values():
            if param.name == "self":
                continue
            ann = param.annotation
            if ann != inspect.Parameter.empty:
                dep_key = get_component_key(ann)
                if dep_key not in container.__dict__:
                    raise ValueError(f"Missing dependency: {dep_key}")
                kwargs[param.name] = container.__dict__[dep_key]

        # Elegir tipo de proveedor
        match provider_type:
            case ProviderType.SINGLETON:
                provider = providers.Singleton(cls, **kwargs)
            case ProviderType.FACTORY:
                provider = providers.Factory(cls, **kwargs)
            case ProviderType.RESOURCE:
                provider = providers.Resource(cls, **kwargs)
            case _:
                raise ValueError(f"Unsupported provider type: {provider_type}")

        container.__dict__[key] = provider
        meta["provider"] = provider  # útil para test o introspección


"""
# container.py
from dependency_injector import containers, providers
from common.component import ComponentRegistry  # Tu sistema de @component
from typing import Iterable
import inspect


class AppContainer(containers.DynamicContainer):
    def __init__(self):
        super().__init__()
        self._built = False

    def _build(self):        
        for name, meta in ComponentRegistry.all().items():
            provider_cls = {
                "singleton": providers.Singleton,
                "factory": providers.Factory,
                "resource": providers.Resource,
            }[meta.scope]
            provider = provider_cls(meta.cls, **meta.dependencies)
            setattr(self, name, provider)

        self._built = True

    def wire(self, modules: Iterable[object]):        
        if not self._built:
            self._build()
        super().wire(modules=modules)

"""
