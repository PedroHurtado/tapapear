import inspect
from typing import Iterable
from dependency_injector import containers, providers
from common.ioc.component import ProviderType, component_registry, get_component_key


class AppContainer(containers.DynamicContainer):
    def __init__(self):
        super().__init__()
        self._built = False

    def _build(self):
        # Primero, crear todos los providers sin dependencias
        for key in component_registry:
            self.__dict__[key] = None

        # Luego, configurar cada provider con sus dependencias
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
                    if dep_key not in component_registry:
                        raise ValueError(f"Missing dependency: {dep_key}")
                    # Referenciar al provider, no al contenedor
                    kwargs[param.name] = getattr(self, dep_key.replace('.', '_'))

            # Crear el provider según el tipo
            match provider_type:
                case ProviderType.SINGLETON:
                    provider = providers.Singleton(cls, **kwargs)
                case ProviderType.FACTORY:
                    provider = providers.Factory(cls, **kwargs)
                case ProviderType.RESOURCE:
                    provider = providers.Resource(cls, **kwargs)
                case _:
                    raise ValueError(f"Unsupported provider type: {provider_type}")

            # Asignar con nombre compatible (reemplazar puntos por guiones bajos)           
            setattr(self, key, provider)
            meta["provider"] = provider

        self._built = True

    def wire(self, modules: Iterable[str]):
        """Wire modules by name"""
        if not self._built:
            self._build()
        super().wire(modules=modules)


container = AppContainer()
