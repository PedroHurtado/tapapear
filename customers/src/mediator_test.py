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
class Repository:
    def save(self):...



@component
class Service(CommandHadler[Request]):
    def __init__(self, repository:Repository):
        self._repository = repository    
    def handler(self, command: Request) -> Response:                                            
        self._repository.save()
        print(command)        
        return Response(id=1)


@inject
def main(mediator:Mediator = deps(Mediator)):
    response = mediator.send(Request(id=1))    
    print(response)


if __name__ == "__main__":    
    container.wire([__name__])
    main()
