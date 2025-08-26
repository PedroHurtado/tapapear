from common.ioc import container, ProviderType, component, deps, inject, AppContainer
from typing import List


@component(provider_type=ProviderType.OBJECT)
class Foo:...


class PipeLine: ...


@component
class Repository:
    def __init__(self):
        pass


@component
class Service:
    def __init__(self, repository: Repository):
        pass


@component
class PipeLineAuth(PipeLine):
    def __init__(self):
        pass


@component
class Mediator:
    def __init__(self, pipelines: List[PipeLine], container: AppContainer):
        self.pipelines = pipelines
        self.service:Service = container.get(Service)
        pass


component(List[PipeLine], provider_type=ProviderType.LIST)


@inject
def main(mediator: Mediator = deps(Mediator), foo = deps(Foo)):
    pass


if __name__ == "__main__":
    container.wire([__name__])
    main()    
