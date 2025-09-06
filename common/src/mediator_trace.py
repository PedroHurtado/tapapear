import asyncio
from uuid import UUID
from common.mediator import Mediator, Command, CommandHadler, LogggerPipeLine
from common.util import get_id
from common.ioc import component, inject,deps, container
from common.domain import BaseEntity, DomainEventContainer, DomainEvent
from common.telemetry import DomainInstrumentor

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


class Request(Command):
    id:UUID

@component
class Service(CommandHadler[Request]):
    async def handler(self, command:Request):        
        User.create(command.id)

def config():
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

@inject
async def controller(request:Request, mediator:Mediator = deps(Mediator)):
    return await mediator.send(request)

if __name__ == "__main__":    
    container.wire([__name__])
    config()
    request = Request(id=get_id())
    asyncio.run(controller(request))
    

    