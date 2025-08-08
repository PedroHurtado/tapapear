from dependency_injector import providers, containers
from dependency_injector.wiring import inject, Provide
import inspect

# Registry global para componentes
_component_registry = {}

def component(name=None, singleton=True):
    """Decorador para auto-registrar componentes."""
    def decorator(cls):
        component_name = name or cls.__name__.lower()
        
        # Analizar constructor para dependencias
        sig = inspect.signature(cls.__init__)
        dependencies = {}
        
        for param_name, param in sig.parameters.items():
            if param_name != 'self' and param.annotation != inspect.Parameter.empty:
                # Buscar provider para el tipo
                dep_name = param.annotation.__name__.lower()
                if dep_name in _component_registry:
                    dependencies[param_name] = _component_registry[dep_name]['provider']
        
        # Crear provider
        if singleton:
            provider = providers.Singleton(cls, **dependencies)
        else:
            provider = providers.Factory(cls, **dependencies)
        
        _component_registry[component_name] = {
            'class': cls,
            'provider': provider,
            'dependencies': dependencies
        }
        
        return cls
    return decorator

def register_components(container_class):
    """Registra todos los componentes en el contenedor."""
    for name, info in _component_registry.items():
        setattr(container_class, name, info['provider'])
    return container_class

@component()
class Redis:
    def __init__(self):
        print('Redis constructor')

@component()
class Service:
    def __init__(self, redis: Redis):
        print('Service constructor')
        self._redis = redis
        
    def handler(self):
        print('Handler ejecutado')

@register_components
class Container(containers.DeclarativeContainer):
    config = providers.Configuration()

# DEBUG: Vamos a ver qué está pasando
print("=== DEBUG CONTAINER ===")
container = Container()
print(f"Container creado: {container}")
print(f"¿Tiene service? {hasattr(container, 'service')}")
print(f"Tipo de service: {type(container.service)}")

# DEBUG: Wiring paso a paso
print("\n=== DEBUG WIRING ===")
try:
    # Intentar diferentes formas de wiring
    import __main__
    result = container.wire(modules=[__main__])
    print(f"Wire result: {result}")
except Exception as e:
    print(f"Error en wiring con __main__: {e}")
    
try:
    import sys
    current_module = sys.modules[__name__]
    result = container.wire(modules=[current_module])
    print(f"Wire con sys.modules result: {result}")
except Exception as e:
    print(f"Error en wiring con sys.modules: {e}")

# La función problemática
print("\n=== FUNCIÓN CON @inject ===")
def foo(
   data: dict,
   service: Service = Provide[Container.service]  # Usar la CLASE, no la instancia
):
    print(f"Service recibido: {service}")
    print(f"Tipo: {type(service)}")
    if hasattr(service, 'handler'):
        service.handler()
    else:
        print(f"ERROR: {service} no tiene handler")

# Probar
print("\n=== EJECUCIÓN ===")
try:
    foo({"name": "Juan"})
except Exception as e:
    print(f"Error esperado: {e}")
    print("¡Te lo dije! 😄")