from common.server import AppBuilder
import logging
if __name__ == "__main__":        

    logging.getLogger("httpx").setLevel(logging.WARNING)
    
    from common.telemetry import DomainInstrumentor
    from common.domain import BaseEntity, DomainEventContainer

    
    DomainInstrumentor().instrument(
        base_entity_class=BaseEntity, domain_event_container_class=DomainEventContainer
    )
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        SimpleSpanProcessor,
        ConsoleSpanExporter,
    )
    

    provider = TracerProvider()
    trace.set_tracer_provider(provider)

    exporter = ConsoleSpanExporter()

    # Procesador que envía cada span al exportador
    span_processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(span_processor)

    AppBuilder().build().run()  
