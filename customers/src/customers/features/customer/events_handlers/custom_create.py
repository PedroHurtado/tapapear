from common.mediator import NotificationHandler
from common.ioc import component
from customers.domain.customer import CustomerCreateEvent
from customers.infrastructure.services import PostService


@component
class CustomerCreateEventHandlers(NotificationHandler[CustomerCreateEvent]):
    def __init__(self, postService: PostService):
        self._service = PostService

    async def handler(self, domain_event: CustomerCreateEvent):
        posts = await self._service.query()
