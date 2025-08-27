import asyncio
from common.ioc import container, component, inject, deps, ProviderType
from common.mediator import (
    Mediator,
    CommandHadler,
    Command,
    pipelines,    
    ignore_pipelines,
    LogggerPipeLine,
    TransactionPipeLine,
)

@component(provider_type=ProviderType.FACTORY)
class Principal:
    def __init__(self):
        print("Principal")

class Request(Command):
    id: int


class Response(Command):
    id: int

@component
class Repository:
    def save(self):...



@component
@pipelines(LogggerPipeLine,TransactionPipeLine)
class Service(CommandHadler[Request]):
    def __init__(self, repository:Repository):
        self._repository = repository  

    @inject  
    async def handler(self, command: Request, principal:Principal = deps(Principal)) -> Response:                                            
        self._repository.save()        
        return Response(id=1)

@inject
async def main(mediator:Mediator = deps(Mediator)):
    request= Request(id=1)
    print(f"petición del usuario {request}")
    response = await mediator.send(request)       
    print(f"devolución a  usuario {response}")    


if __name__ == "__main__":    
    container.wire([__name__])
    asyncio.run(main())
