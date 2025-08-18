from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.utils import generate_unique_id
from common.confg import Config
from common.context import Context
from common.ioc import AppContainer


class CustomFastApi(FastAPI):
    def __init__(
        self,
        *,
        config: Config,
        context: Context,
        container: AppContainer,
        debug=False,
        routes=None,
        title="FastAPI",
        summary=None,
        description="",
        version="0.1.0",
        openapi_url="/openapi.json",
        openapi_tags=None,
        servers=None,
        dependencies=None,
        default_response_class=JSONResponse,
        redirect_slashes=True,
        docs_url="/docs",
        redoc_url="/redoc",
        swagger_ui_oauth2_redirect_url="/docs/oauth2-redirect",
        swagger_ui_init_oauth=None,
        middleware=None,
        exception_handlers=None,
        on_startup=None,
        on_shutdown=None,
        lifespan=None,
        terms_of_service=None,
        contact=None,
        license_info=None,
        openapi_prefix="",
        root_path="",
        root_path_in_servers=True,
        responses=None,
        callbacks=None,
        webhooks=None,
        deprecated=None,
        include_in_schema=True,
        swagger_ui_parameters=None,
        generate_unique_id_function=generate_unique_id,
        separate_input_output_schemas=True,
        **extra
    ):
        super().__init__(
            debug=debug,
            routes=routes,
            title=title,
            summary=summary,
            description=description,
            version=version,
            openapi_url=openapi_url,
            openapi_tags=openapi_tags,
            servers=servers,
            dependencies=dependencies,
            default_response_class=default_response_class,
            redirect_slashes=redirect_slashes,
            docs_url=docs_url,
            redoc_url=redoc_url,
            swagger_ui_oauth2_redirect_url=swagger_ui_oauth2_redirect_url,
            swagger_ui_init_oauth=swagger_ui_init_oauth,
            middleware=middleware,
            exception_handlers=exception_handlers,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            lifespan=lifespan,
            terms_of_service=terms_of_service,
            contact=contact,
            license_info=license_info,
            openapi_prefix=openapi_prefix,
            root_path=root_path,
            root_path_in_servers=root_path_in_servers,
            responses=responses,
            callbacks=callbacks,
            webhooks=webhooks,
            deprecated=deprecated,
            include_in_schema=include_in_schema,
            swagger_ui_parameters=swagger_ui_parameters,
            generate_unique_id_function=generate_unique_id_function,
            separate_input_output_schemas=separate_input_output_schemas,
            **extra
        )
        self._config = config
        self._context = context
        self._container = container

    @property
    def config(self) -> Config:
        return self._config

    @property
    def context(self) -> Context:
        return self._context

    @property
    def container(self) -> AppContainer:
        return self._container
