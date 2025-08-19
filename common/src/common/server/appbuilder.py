from common.ioc import container, AppContainer
from common.server import get_feature_routers
from common.context import context
from common.confg import Config, config
from common.context import context, Context
from common.openapi import setup_custom_openapi
from common.security import setup_security_dependencies
from common.middelwares import SUPPORT_MIDDELWARES
from .custom_fastapi import CustomFastApi
import uvicorn


from contextlib import asynccontextmanager

def setup_middelwares(app:CustomFastApi):
    middelwares = app.config.middlewares
    for mw in middelwares:
        middleware_cls = SUPPORT_MIDDELWARES[mw.class_]
        app.add_middleware(middleware_cls, **mw.options)


@asynccontextmanager
async def _lifespan(app: CustomFastApi):
    try:        
        setup_security_dependencies(app)
        app.context.allow_anonymous_routes.update(app.context.docs_path)        
    except Exception as e:
        raise e
    yield
    app.container.unwire()


class AppBuilder:
    """
    Clase para construir y ejecutar una aplicación FastAPI utilizando
    un patrón de diseño fluido ("fluent builder").
    """

    def __init__(
        self,
        config: Config = config(),
        context: Context = context,
        container: AppContainer = container,
    ):

        self._host = "127.0.0.1"        
        self._app = CustomFastApi(
            config=config, context=context, container=container, lifespan=_lifespan
        )

    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""

        routers = get_feature_routers(self._app.config.features)

        if not routers:
            print("⚠ Advertencia: No se encontraron routers en las features")

        # Registrar routers
        
        for router in routers:
            try:
                self._app.include_router(router)
            except Exception as e:
                raise e

        # Registras modules en IOC
        modules = self._app.context.modules        
        try:            
            self._app.container.wire(modules)            
        except Exception as e:
            raise e

        print(f"  -  Routers registrados {len(routers)}")
        print(f"  -  DI registrados {len(modules)}")

        setup_custom_openapi(self._app)
        
        setup_middelwares(self._app)
                        
        self._app.exception_handlers.clear()

    def run(self, host: str = "127.0.0.1", port: int = 8080) -> None:

        self.build()

        # Usar los valores pasados como parámetros o los configurados en la clase
        final_host = host or self._host
        final_port = self._app.config.port or port

        print(f"🚀 Servidor en http://{final_host}:{final_port}")
        uvicorn.run(self._app, host=final_host, port=final_port)
