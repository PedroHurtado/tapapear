import functools
from typing import Dict, Callable, Collection, Any
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor

class DomainInstrumentor(BaseInstrumentor):
    _original_methods: Dict[type, Dict[str, Callable]] = {}
    _original_init_subclasses: Dict[type, Callable] = {}
    _is_instrumented: bool = False
    _base_entity_class: type | None = None
    _domain_event_container_class: type | None = None

    def instrumentation_dependencies(self) -> Collection[str]:
        return ["opentelemetry-api"]

    def _instrument(self, **kwargs):
        DomainInstrumentor._is_instrumented = True
        base_entity_class = kwargs.get("base_entity_class")
        domain_event_container_class = kwargs.get("domain_event_container_class")
        if not base_entity_class or not domain_event_container_class:
            raise ValueError("Se requieren base_entity_class y domain_event_container_class")
        DomainInstrumentor._base_entity_class = base_entity_class
        DomainInstrumentor._domain_event_container_class = domain_event_container_class
        self._patch_base_classes()

    def _uninstrument(self, **kwargs):
        DomainInstrumentor._is_instrumented = False
        for base_class, original_init_subclass in DomainInstrumentor._original_init_subclasses.items():
            base_class.__init_subclass__ = original_init_subclass
        for entity_class, methods in DomainInstrumentor._original_methods.items():
            for method_name, original_method in methods.items():
                setattr(entity_class, method_name, original_method)
        DomainInstrumentor._original_methods.clear()
        DomainInstrumentor._original_init_subclasses.clear()
        DomainInstrumentor._base_entity_class = None
        DomainInstrumentor._domain_event_container_class = None

    def _patch_base_classes(self):
        base_entity_class = DomainInstrumentor._base_entity_class
        domain_event_container_class = DomainInstrumentor._domain_event_container_class

        if base_entity_class not in DomainInstrumentor._original_init_subclasses:
            DomainInstrumentor._original_init_subclasses[base_entity_class] = base_entity_class.__init_subclass__

            def instrumented_init_subclass(cls, **kwargs):
                original = DomainInstrumentor._original_init_subclasses[base_entity_class]
                original(**kwargs)
                if DomainInstrumentor._is_instrumented:
                    DomainInstrumentor.instrument_entity_class(cls)

            base_entity_class.__init_subclass__ = classmethod(instrumented_init_subclass)

        self._patch_domain_event_container(domain_event_container_class)

    def _patch_domain_event_container(self, domain_event_container_class: type):
        if domain_event_container_class not in DomainInstrumentor._original_methods:
            DomainInstrumentor._original_methods[domain_event_container_class] = {}

        # Patch __init__
        if "__init__" not in DomainInstrumentor._original_methods[domain_event_container_class]:
            original_init = domain_event_container_class.__init__

            def instrumented_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                if not hasattr(self, "_domain_events"):
                    self._domain_events = []

            DomainInstrumentor._store_original_method(domain_event_container_class, "__init__", original_init)
            domain_event_container_class.__init__ = instrumented_init

        # Patch add_event
        if hasattr(domain_event_container_class, "add_event"):
            original_add_event = domain_event_container_class.add_event

            def instrumented_add_event(self, event, *args, **kwargs):
                if not hasattr(self, "_domain_events"):
                    self._domain_events = []
                result = original_add_event(self, event, *args, **kwargs)
                DomainInstrumentor.trace_event_added(event)
                return result

            DomainInstrumentor._store_original_method(domain_event_container_class, "add_event", original_add_event)
            domain_event_container_class.add_event = instrumented_add_event

        # Patch clear_events
        if hasattr(domain_event_container_class, "clear_events"):
            original_clear_events = domain_event_container_class.clear_events

            def instrumented_clear_events(self, *args, **kwargs):
                events_count = len(getattr(self, "_domain_events", []))
                result = original_clear_events(self, *args, **kwargs)
                DomainInstrumentor.trace_events_cleared(events_count)
                return result

            DomainInstrumentor._store_original_method(
                domain_event_container_class, "clear_events", original_clear_events
            )
            domain_event_container_class.clear_events = instrumented_clear_events

    @classmethod
    def is_instrumented(cls) -> bool:
        return cls._is_instrumented

    @classmethod
    def instrument_entity_class(cls, entity_class: type) -> None:
        domain_event_container_class = cls._domain_event_container_class
        for name, attr in entity_class.__dict__.items():  # <--- IMPORTANTE: usar __dict__ para detectar classmethods
            if name.startswith("_"):
                continue
            if domain_event_container_class and hasattr(domain_event_container_class, name):
                continue

            original_method = None
            is_classmethod = False
            is_staticmethod = False

            if isinstance(attr, classmethod):
                original_method = attr.__func__
                is_classmethod = True
            elif isinstance(attr, staticmethod):
                original_method = attr.__func__
                is_staticmethod = True
            elif callable(attr):
                original_method = attr

            if original_method:
                cls._store_original_method(entity_class, name, attr)
                instrumented = cls._create_instrumented_method(original_method, entity_class, name, is_classmethod, is_staticmethod)
                if is_classmethod:
                    instrumented = classmethod(instrumented)
                elif is_staticmethod:
                    instrumented = staticmethod(instrumented)
                setattr(entity_class, name, instrumented)

    @classmethod
    def _store_original_method(cls, entity_class: type, method_name: str, method: Callable):
        if entity_class not in cls._original_methods:
            cls._original_methods[entity_class] = {}
        cls._original_methods[entity_class][method_name] = method

    @classmethod
    def _create_instrumented_method(cls, func: Callable, entity_class: type, method_name: str, is_classmethod=False, is_staticmethod=False) -> Callable:
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracer = trace.get_tracer(__name__)
            span_name = f"domain.{entity_class.__name__}.{method_name}"
            with tracer.start_as_current_span(span_name) as span:
                try:
                    result = func(*args, **kwargs)

                    # Instancia correcta
                    instance = None
                    if is_classmethod or is_staticmethod:
                        instance = result
                    elif args:
                        instance = args[0]

                    entity_id = getattr(instance, "id", getattr(instance, "_id", "unknown")) if instance else "unknown"
                    events_after = len(getattr(instance, "_domain_events", [])) if instance else 0

                    span.set_attributes({
                        "entity.type": entity_class.__name__,
                        "entity.method": method_name,                        
                        "entity.id": str(entity_id),
                        "entity.has_events": events_after > 0
                    })

                    if events_after > 0:
                        event_types = [getattr(e, "event_type", e.__class__.__name__) for e in instance._domain_events]
                        span.set_attribute("entity.event_types", ",".join(event_types))

                    
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))                    
                    raise

        return wrapper

    @classmethod
    def trace_event_added(cls, event: Any):
        if not cls.is_instrumented():
            return
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.add_event(
                "domain_event_generated",
                attributes={
                    "event.type": getattr(event, "event_type", event.__class__.__name__),
                    "event.id": str(getattr(event, "id", "unknown")),
                    "event.aggregate": getattr(event, "aggregate", "unknown"),
                    "event.aggregate_id": str(getattr(event, "aggregate_id", "unknown")),
                    "event.timestamp": str(getattr(event, "timestamp", "unknown"))
                }
            )

    @classmethod
    def trace_events_cleared(cls, events_count: int):
        if not cls.is_instrumented():
            return
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.add_event(
                "domain_events_cleared",
                attributes={"events_cleared_count": events_count}
            )
