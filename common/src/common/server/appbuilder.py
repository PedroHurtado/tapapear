from common.ioc import container, AppContainer
from common.server import get_feature_routers
from common.context import context
from common.confg import Config, config
from common.context import context, Context
from common.openapi import setup_custom_openapi
from common.security import setup_security_dependencies
from .custom_fastapi import CustomFastApi
import uvicorn


from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: CustomFastApi):
    app.container.wire(app.context.modules)
    setup_security_dependencies(app)
    app.context.allow_anonymous_routes.update(app.context.docs_path)
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

        self._host = "0.0.0.0"        
        self._app = CustomFastApi(
            config=config, context=context, container=container, lifespan=_lifespan
        )

    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""

        routers = get_feature_routers(self._app.config.features)

        if not routers:
            print("⚠ Advertencia: No se encontraron routers en las features")

        # Registrar routers
        print("Registrando routers...")
        for router in routers:
            try:
                self._app.include_router(router)
            except Exception as e:
                raise e

        print(f"  - {len(routers)} routers registrados")

        setup_custom_openapi(self._app)
        
        #TODO:middelwares

        self._app.exception_handlers.clear()

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:

        self.build()

        # Usar los valores pasados como parámetros o los configurados en la clase
        final_host = host or self._host
        final_port = port or self._app.config.port

        print(f"🚀 Iniciando servidor en http://{final_host}:{final_port}")
        uvicorn.run(self._app, host=final_host, port=final_port)
