from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject
from typing import Annotated

class Redis:
    def __init__(self):
        pass
class Service:
    def  __init__(self, redis:Redis):
        pass


class Container(containers.DeclarativeContainer):
    redis = providers.Singleton(Redis)
    service = providers.Singleton(
        Service,
        redis = redis
    )


# You can place marker on parameter default value
@inject
def main(service: Service = Provide[Container.service]) -> None: 
    print (type(service))



# Also, you can place marker with typing.Annotated
@inject
def main_with_annotated(
    service: Annotated[Service, Provide[Container.service]]
) -> None: ...


if __name__ == "__main__":
    container = Container()
    container.wire(modules=[__name__])

    main()
    main_with_annotated()