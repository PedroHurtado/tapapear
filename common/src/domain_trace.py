from common.domain import BaseEntity, DomainEventContainer, DomainEvent
from common.telemetry import DomainInstrumentor
from common.util import get_id
from uuid import UUID

DomainInstrumentor().instrument(
    base_entity_class=BaseEntity, domain_event_container_class=DomainEventContainer
)


class UserCreateEvent(DomainEvent):
    @staticmethod
    def create(aggregate_id:UUID)->"UserCreateEvent":
        return UserCreateEvent(aggregate="User", aggregate_id=aggregate_id)

class User(BaseEntity,DomainEventContainer):
    @classmethod
    def create(cls, id: UUID)->"User":
        instance =  cls(id)
        instance.add_event(UserCreateEvent.create(instance.id))
        return instance




if __name__ == "__main__":
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

    user = User.create(get_id())  
    
