import asyncio
from uuid import UUID
from common.mediator import (
    Mediator, Command, CommandHadler, NotificationHandler, EventBus
)
from common.util import get_id
from common.ioc import component, inject, deps, container
from common.domain import BaseEntity, DomainEventContainer, DomainEvent
from common.telemetry import DomainInstrumentor
from common.context import context

DomainInstrumentor().instrument(
    base_entity_class=BaseEntity,
    domain_event_container_class=DomainEventContainer
)

class UserCreateEvent(DomainEvent):
    @staticmethod
    def create(aggregate_id: UUID) -> "UserCreateEvent":
        return UserCreateEvent(aggregate="User", aggregate_id=aggregate_id)

@component
class RepositoryOutBux:
    def __init__(self, event_bus:EventBus):
        self._event_bus=event_bus
    async def save(domain_event:UserCreateEvent):
        pass


@component
class UserCreateNoficationHandler(NotificationHandler[UserCreateEvent]):
    def __init__(self,respostitory:RepositoryOutBux):        
        self._repository = RepositoryOutBux
    async def handler(self, domain_event: UserCreateEvent):
        await self._repository.save(domain_event)

class User(BaseEntity, DomainEventContainer):
    @classmethod
    def create(cls, id: UUID) -> "User":
        instance = cls(id)
        instance.add_event(UserCreateEvent.create(instance.id))
        return instance

class Request(Command):
    id: UUID

@component
class Repository:
    def __init__(self, event_bus:EventBus):
        self._event_bus = event_bus
    async def save(self, user: User):       
        for event in user.get_events():
            await self._event_bus.notify(event)
        user.clear_events()
        return user

@component
class Service(CommandHadler[Request]):
    def __init__(self, repository: Repository):
        super().__init__()
        self._repository = repository        
    
    async def handler(self, command: Request)->User:
        user = User.create(command.id)
        
        # Guardar el usuario
        await self._repository.save(user)       
        
        return user

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
    span_processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(span_processor)

@inject
async def controller(request: Request, mediator: Mediator = deps(Mediator)):
    user:User =  await mediator.send(request)    

if __name__ == "__main__":
    container.wire(context.modules)
    config()
    request = Request(id=get_id())
    asyncio.run(controller(request))