from common.ioc import container, component, inject, deps
from common.mediator import (
    Mediator,
    CommandHadler,
    Command,
    pipelines,
    LogggerPipeLine,
    TransactionPipeLine,
)

@pipelines(LogggerPipeLine)
class Request(Command):
    id: int


class Response(Command):
    id: int


@component
class Service(CommandHadler[Request]):
    def handler(self, command: Request) -> Response:
        print(command)
        return Response(id=1)


@inject
def main(mediator:Mediator = deps(Mediator)):
    response = mediator.send(Request(id=1))
    print(response)


if __name__ == "__main__":
    container.wire([__name__])
    main()
