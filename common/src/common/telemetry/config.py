import logging
import structlog
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor


class FilteringSpanProcessor(SpanProcessor):
    """Span processor that filters out unwanted ASGI internal spans."""

    def __init__(self, wrapped_processor: SpanExporter):
        self.wrapped_processor = SimpleSpanProcessor(wrapped_processor)

    def on_start(self, span, parent_context=None):
        self.wrapped_processor.on_start(span, parent_context)

    def on_end(self, span):
        span_name = span.name
        should_export = not (
            "http send" in span_name
            or "http receive" in span_name
            or "http.response.start" in span_name
            or "http.response.body" in span_name
            or span.attributes.get("asgi.event.type") is not None
        )
        if should_export:
            self.wrapped_processor.on_end(span)

    def shutdown(self):
        return self.wrapped_processor.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self.wrapped_processor.force_flush(timeout_millis)


class TracerNameProcessor(SpanProcessor):
    """Span processor that injects tracer_name attribute into each span."""

    def on_start(self, span, parent_context=None):
        if span.instrumentation_scope and span.instrumentation_scope.name:            
            span.set_attribute("tracer_name", str(span.instrumentation_scope.name))

    def on_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis=30000):
        pass


def add_service_name(service_name: str, service_version: str):
    """Create a processor to add service info to all structlog events."""
    def processor(logger, method_name, event_dict):
        event_dict["service_name"] = service_name
        event_dict["service_version"] = service_version

        span = trace.get_current_span()
        if span and span.is_recording():
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
            event_dict["span_name"] = span.name
            event_dict["tracer_name"] = span.instrumentation_scope.name
        return event_dict
    return processor


def configure_structlog(service_name: str, service_version: str):
    """Configure structlog with OpenTelemetry integration."""
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="ISO"),
            add_service_name(service_name, service_version),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_telemetry(service_name: str, service_version: str = "1.0.0", fastapi_app=None):
    """Setup OpenTelemetry configuration."""
    resource = Resource.create({
        "service.name": service_name,
        "service.version": service_version,
    })

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(TracerNameProcessor())
    provider.add_span_processor(
        FilteringSpanProcessor(ConsoleSpanExporter())
    )
    trace.set_tracer_provider(provider)

    if fastapi_app:
        FastAPIInstrumentor.instrument_app(fastapi_app)
    else:
        FastAPIInstrumentor().instrument()

    HTTPXClientInstrumentor().instrument()
    LoggingInstrumentor().instrument()

    configure_structlog(service_name, service_version)

    logger = structlog.get_logger(__name__)
    logger.info("Telemetry initialized", service=service_name, version=service_version)


def get_tracer(name: str):
    """Get a tracer for creating custom spans."""
    return trace.get_tracer(name)


def get_logger(name: str = None):
    """Get a structured logger."""
    return structlog.get_logger(name)
