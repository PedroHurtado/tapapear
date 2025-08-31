from opentelemetry import trace
import functools
import asyncio

def traced_class(metodos=None):
    """Decorador para instrumentar una clase completa (sync y async)"""
    def decorator(cls):
        tracer = trace.get_tracer(__name__)
        
        target_methods = metodos or [name for name in dir(cls) 
                                   if not name.startswith('_') and callable(getattr(cls, name))]
        
        for method_name in target_methods:
            if hasattr(cls, method_name):
                original_method = getattr(cls, method_name)
                
                def create_traced_method(original, name):
                    if asyncio.iscoroutinefunction(original):
                        # Async wrapper
                        @functools.wraps(original)
                        async def async_wrapper(self, *args, **kwargs):
                            with tracer.start_as_current_span(f"{cls.__name__}.{name}") as span:
                                span.set_attribute("method_name", name)
                                span.set_attribute("method_type", "async")
                                return await original(self, *args, **kwargs)
                        return async_wrapper
                    else:
                        # Sync wrapper
                        @functools.wraps(original)
                        def sync_wrapper(self, *args, **kwargs):
                            with tracer.start_as_current_span(f"{cls.__name__}.{name}") as span:
                                span.set_attribute("method_name", name)
                                span.set_attribute("method_type", "sync")
                                return original(self, *args, **kwargs)
                        return sync_wrapper
                
                setattr(cls, method_name, create_traced_method(original_method, method_name))
        
        return cls
    return decorator