from common.mediator import NotificationHandler
from common.ioc import component
from customers.domain.customer import CustomerCreateEvent

@component
class CustomerCreateEventHandlers(NotificationHandler[CustomerCreateEvent]):
    async def handler(self, domain_event:CustomerCreateEvent):
        pass
        