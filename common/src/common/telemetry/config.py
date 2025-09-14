import logging
import structlog
import json


from datetime import datetime, timezone
from typing import Sequence, Optional, Mapping, Any, List

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider, SpanProcessor, ReadableSpan
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor,ResponseInfo
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from common.ioc import inject,deps
from common.security import Principal

# --------------------------------------
# Procesador que filtra spans de ruido
# (mantiene tu lógica original)
# --------------------------------------
class FilteringSpanProcessor(SpanProcessor):
    """
    Procesa spans aplicando un filtro y delega en otro SpanProcessor (Batch).
    Úsalo para eliminar spans internos ASGI/HTTP que no aportan.
    """

    def __init__(self, inner_processor: SpanProcessor):
        self._inner = inner_processor

    @inject
    def on_start(self, span, parent_context=None, principal:Principal = deps(Principal)):                
        
        if principal:
            span.set_attribute("enduser.id", str(principal.id))                        
            span.set_attribute("user.role", principal.role) 
            if principal.tenant:
                span.set_attribute("app.tenant.id", str(principal.tenant)) 
        else:
            pass
        if span.kind == trace.SpanKind.SERVER or span.kind == trace.SpanKind.CLIENT:        
            if span.status.status_code == StatusCode.UNSET:
                span.set_status(Status(StatusCode.OK))

        self._inner.on_start(span, parent_context)

    def on_end(self, span, principal:Principal = deps(Principal)):  
                         
        noisy = span.attributes.get("asgi.event.type") is not None        
        if not noisy:
            self._inner.on_end(span)        






# --------------------------------------
# structlog + correlación con trazas
# --------------------------------------

def add_service_name(service_name: str, service_version: str):
    """Processor de structlog para añadir servicio + correlación OTel."""

    def processor(logger, method_name, event_dict):
        event_dict["service_name"] = service_name
        event_dict["service_version"] = service_version

        span = trace.get_current_span()
        if span and span.is_recording():
            ctx = span.get_span_context()
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
            event_dict["span_name"] = span.name
        return event_dict

    return processor


def configure_structlog(service_name: str, service_version: str):
    # Suprimir logs de uvicorn/fastapi para evitar exceptions en consola
    
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    logging.basicConfig(
        format="%(message)s",
        level=logging.INFO,
    )
    

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


def custom_response_hook(span: trace.Span, scope: dict[str, Any], message: dict[str, Any]):    
    if not span.is_recording():
        return    
    if message.get('type') == 'http.response.start':
        status_code = message.get('status')
        
        if status_code is not None:
            status_int = int(status_code)
            
            # Buscar el span padre (el root que NO será filtrado)
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                if 400 <= status_int < 500:
                    current_span.set_status(Status(StatusCode.ERROR, f"HTTP {status_int}"))
                else:
                    current_span.set_status(Status(StatusCode.OK))
            
            # También modificar el span actual por si acaso
            if 400 <= status_int < 500:
                span.set_status(Status(StatusCode.ERROR, f"HTTP {status_int}"))
            else:
                span.set_status(Status(StatusCode.OK))



async def async_response_hook(span: trace.Span, request, response: ResponseInfo):
    if span.is_recording() and response.status_code <400:        
        span.set_status(Status(StatusCode.OK))
        
    



# --------------------------------------
# Setup OTel (manteniendo tu API)
# --------------------------------------
def setup_telemetry(
    service_name: str, service_version: str = "1.0.0", fastapi_app=None
):
    """
    Configura OpenTelemetry con:
    - Resource del servicio
    - BatchSpanProcessor + FilteringSpanProcessor
    - Exportador DevConsole agrupado
    - Instrumentación FastAPI, httpx y logging
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
        }
    )

    provider = TracerProvider(resource=resource)

    console_exporter = ConsoleSpanExporter()

    # Procesador simple (sin batching) - salida inmediata
    simple_processor = SimpleSpanProcessor(console_exporter)

    # Aplicar tu filtro al procesador simple
    provider.add_span_processor(FilteringSpanProcessor(simple_processor))

    trace.set_tracer_provider(provider)

    # Instrumentación FastAPI
    if fastapi_app:
        FastAPIInstrumentor.instrument_app(
            fastapi_app,            
            excluded_urls="/docs.*,/redoc,/openapi.json" 
        )
    else:
        FastAPIInstrumentor().instrument()

    # Instrumentación HTTPX con hooks mejorados
    HTTPXClientInstrumentor().instrument(
        async_response_hook=async_response_hook
    )
    
    LoggingInstrumentor().instrument()

    # structlog con logging suprimido
    configure_structlog(service_name, service_version)

    # Mensaje de arranque
    logger = structlog.get_logger(__name__)
    logger.info("Telemetry initialized", service=service_name, version=service_version)


# --------------------------------------
# Helpers públicos
# --------------------------------------
def get_tracer(name: str):
    return trace.get_tracer(name)


def get_logger(name: str = None):
    return structlog.get_logger(name)


