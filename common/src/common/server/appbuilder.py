from fastapi import Request
from common.ioc import container, AppContainer
from common.server import get_feature_routers
from common.context import context
from common.confg import Config, config
from common.context import context, Context
from common.openapi import setup_custom_openapi
from common.security import setup_security_dependencies
from common.middelwares import SUPPORT_MIDDELWARES
from .custom_fastapi import CustomFastApi
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import uvicorn


from contextlib import asynccontextmanager


def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


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

        self._config = config
        self._context = context
        self._container = container
        self._app = None

    def _setup_health(self, app: CustomFastApi):
        app.router.routes.append(
            Route(
                path="/health",
                endpoint=health,
                methods=["GET", "HEAD"],
                name="health",
            )
        )

    def _setup_middelwares(self, app: CustomFastApi):

        middelwares = app.config.middlewares
        for mw in middelwares:
            middleware_cls = SUPPORT_MIDDELWARES[mw.class_]
            app.add_middleware(middleware_cls, **mw.options)

    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""

        self._app = CustomFastApi(
            config=self._config,
            context=self._context,
            container=self._container,
            lifespan=_lifespan,
        )

        routers = get_feature_routers(self._app.config.features)

        # Registrar routers
        if not self._config.env.openapi:
            self._app.routes.clear()

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

        if self._config.env.openapi:
            setup_custom_openapi(self._app)
        else:
            self._app.openapi = lambda: None

        self._setup_health(self._app)

        self._setup_middelwares(self._app)

        self._app.exception_handlers.clear()

        return self

    def run(self, port: int = 8080) -> None:
        if self._app is None:
            self.build()

        final_host = "127.0.0.1"
        final_port = self._app.config.port or port
        uvicorn_config = {
            "host": final_host,
            "port": final_port,
        }

        reload = self._config.env.reload
        workers = 1 if reload else 4

        #uvicorn_config.update({"reload": reload})

        print(f"🚀 Servidor en http://{final_host}:{final_port}")

        #uvicorn.run("main:app", **uvicorn_config)
        uvicorn.run(self._app, **uvicorn_config)

    @property
    def app(self) -> CustomFastApi:
        if self._app == None:
            self.build()
        return self._app
