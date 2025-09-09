from common.server import AppBuilder
import logging

if __name__ == "__main__":
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from common.telemetry import (
        DomainInstrumentor,
        TreeConsoleSpanExporter,
        FilteringSpanProcessor,
    )
    from common.domain import BaseEntity, DomainEventContainer
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Instrumentación del dominio
    DomainInstrumentor().instrument(
        base_entity_class=BaseEntity, domain_event_container_class=DomainEventContainer
    )

    builder = AppBuilder().build()

    # ---------- Configuración de OpenTelemetry ----------
    tracer_provider = TracerProvider()
    trace.set_tracer_provider(tracer_provider)

    tree_exporter = TreeConsoleSpanExporter(show_attributes=True)
    tracer_provider.add_span_processor(FilteringSpanProcessor(BatchSpanProcessor(tree_exporter)))

    # Instrumentación FastAPI con el TracerProvider ya configurado
    FastAPIInstrumentor.instrument_app(
        builder.app, excluded_urls="/docs.*,/redoc,/openapi.json"
    )

    HTTPXClientInstrumentor().instrument()

    # Ejecutar app
    builder.run()
