import inspect
from collections import defaultdict, deque
from typing import Iterable, get_origin, get_args, Type, TypeVar
from dependency_injector import containers, providers
from common.ioc.component import ProviderType, get_component_key, component
from common.context import context

T = TypeVar("T")


class AppContainer(containers.DynamicContainer):
    def __init__(self):
        super().__init__()
        self._built = False

    def _build(self):
        component_registry = context.component_registry

        # --- 1) Recoger metadatos y dependencias declaradas por anotaciones ---
        # node_info[key] = {
        #   "cls", "provider_type", "value", "deps": set[str],
        #   "param_map": {dep_key: param_name}, "list_base": Type|None, "list_members": [keys]
        # }
        node_info = {}
        for key, meta in component_registry.items():
            cls = meta["cls"]
            provider_type = meta["provider_type"]
            value = meta.get("value", None)

            deps = set()
            param_map = {}

            # OBJECT no tiene dependencias por anotaciones
            if provider_type != ProviderType.OBJECT:
                # Soporta clases y callables (factories)
                if inspect.isclass(cls):
                    sig = inspect.signature(cls.__init__)
                    params = (p for p in sig.parameters.values() if p.name != "self")
                elif callable(cls):
                    sig = inspect.signature(cls)
                    params = sig.parameters.values()
                else:
                    params = []

                for p in params:
                    if p.annotation != inspect.Parameter.empty:
                        dep_key = get_component_key(p.annotation)
                        if dep_key not in component_registry:
                            raise ValueError(f"Missing dependency: {dep_key}")
                        deps.add(dep_key)
                        param_map[dep_key] = p.name

            # Info base del nodo
            node_info[key] = {
                "cls": cls,
                "provider_type": provider_type,
                "value": value,
                "deps": deps,
                "param_map": param_map,
                "list_base": None,
                "list_members": [],
            }

        # --- 2) Para LIST: añadir dependencias a todos los miembros (subclases) ---
        # LIST depende de cada provider de clase que sea subclase del base_class.
        for key, info in node_info.items():
            if info["provider_type"] == ProviderType.LIST:
                list_type = info["cls"]
                if hasattr(list_type, "__origin__") and get_origin(list_type) is list:
                    base_class = get_args(list_type)[0]
                    info["list_base"] = base_class
                else:
                    raise ValueError(
                        f"LIST component {key} must be of type List[BaseClass]"
                    )

                members = []
                for comp_key, comp_meta in component_registry.items():
                    if comp_key == key:
                        continue
                    comp_cls = comp_meta["cls"]
                    # Solo consideramos clases registradas (igual que tu versión original)
                    if (
                        inspect.isclass(comp_cls)
                        and comp_cls != info["list_base"]
                        and issubclass(comp_cls, info["list_base"])
                        and comp_meta["provider_type"] != ProviderType.LIST
                    ):
                        members.append(comp_key)

                # Guardar miembros (orden estable por aparición en el registro)
                info["list_members"] = members
                # LIST depende de todos sus miembros (asegura que existan antes)
                info["deps"].update(members)

        # --- 3) Construir grafo y orden topológico ---
        deps_by_node = {k: set(v["deps"]) for k, v in node_info.items()}
        dependents_by_dep = defaultdict(set)
        for node, deps in deps_by_node.items():
            for d in deps:
                dependents_by_dep[d].add(node)

        indegree = {k: len(deps) for k, deps in deps_by_node.items()}
        queue = deque([k for k in component_registry.keys() if indegree.get(k, 0) == 0])
        resolved = set()

        # --- 4) Resolver en orden topológico y crear providers ---
        while queue:
            key = queue.popleft()
            info = node_info[key]
            cls = info["cls"]
            provider_type = info["provider_type"]
            value = info["value"]

            # Construir kwargs desde param_map usando providers ya creados
            kwargs = {}
            if provider_type != ProviderType.OBJECT and info["param_map"]:
                for dep_key, param_name in info["param_map"].items():
                    dep_provider = getattr(self, dep_key, None)
                    if dep_provider is None:
                        raise AttributeError(
                            f"Dependency provider '{dep_key}' not found when building '{key}'"
                        )
                    kwargs[param_name] = dep_provider

            # Crear provider según tipo
            if provider_type == ProviderType.SINGLETON:
                provider = providers.Singleton(cls, **kwargs)
            elif provider_type == ProviderType.FACTORY:
                provider = providers.Factory(cls, **kwargs)
            elif provider_type == ProviderType.RESOURCE:
                provider = providers.Resource(cls, **kwargs)
            elif provider_type == ProviderType.OBJECT:
                provider = providers.Object(value)
            elif provider_type == ProviderType.LIST:
                # Todos los miembros ya deben estar disponibles por el orden topológico
                member_providers = []
                for m_key in info["list_members"]:
                    mp = getattr(self, m_key, None)
                    if mp is not None:
                        member_providers.append(mp)
                provider = providers.List(*member_providers)
            else:
                raise ValueError(f"Unsupported provider type: {provider_type}")

            setattr(self, key, provider)
            component_registry[key]["provider"] = provider
            resolved.add(key)

            # Disminuir indegree de dependientes y encolar los que queden en 0
            for dependent in dependents_by_dep.get(key, ()):
                indegree[dependent] -= 1
                if indegree[dependent] == 0 and dependent not in resolved:
                    queue.append(dependent)

        # Verificación de cierre: detectar ciclos o dependencias imposibles
        if len(resolved) != len(component_registry):
            pending = [k for k in component_registry.keys() if k not in resolved]
            details = {k: sorted(deps_by_node[k]) for k in pending}
            raise RuntimeError(
                f"Unresolved components (possible cycle or missing deps): {pending}. "
                f"Deps: {details}"
            )

        self._built = True

    def get(self, cls: Type[T]) -> T:
        """Devuelve la instancia asociada a un tipo registrado en el contenedor."""
        component_registry = context.component_registry
        key = get_component_key(cls)

        if key not in component_registry:
            raise ValueError(f"Component {cls} no está registrado en el contenedor")

        provider = getattr(self, key, None)
        if provider is None:
            raise RuntimeError(f"Provider para {cls} no está disponible")

        return provider()

    def wire(self, modules: Iterable[str]):
        if not self._built:
            self._build()
        super().wire(modules=modules)

    def unwire(self):
        super().unwire()


# Instancia global del contenedor
container = AppContainer()

# Registrar el propio contenedor como OBJECT
component(AppContainer, provider_type=ProviderType.OBJECT, value=container)
