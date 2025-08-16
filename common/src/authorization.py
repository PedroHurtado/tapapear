import inspect
from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import HTTPBearer
from fastapi.routing import APIRoute
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.exceptions import ValidationException

from pydantic import BaseModel,Field
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Dict, Optional, Callable, Any, Sequence, Union, List
from functools import wraps

from starlette.types import ASGIApp, Receive, Scope, Send, Message
from datetime import datetime, timezone
from common.ioc import AppContainer,component,ProviderType, inject, deps
from common.context import set_app_context, Context
import json
import logging



set_app_context(Context())

@asynccontextmanager
async def lifespan(app: FastAPI):    

    module_names = [__name__]  
    container = AppContainer()
    container.wire(module_names)    

    setup_security_dependencies(app)
    _allow_anonymous_routes.update(DOCS_PATHS) 
          
    yield

    
# create app
app = FastAPI(
    lifespan=lifespan,
    title="Mi API con Auth",
    description="Ejemplo con autenticación automática",
    version="1.0.0",
)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Constantes y estado global
# ============================================================
principal_ctx: ContextVar[Optional["Principal"]] = ContextVar("principal", default=None)

_allow_anonymous_routes: set[tuple[str, str]] = set()
_authorize_routes: set[tuple[str, str]] = set()

def allow_anonymous(func: Callable):
    """Marca una ruta para permitir acceso sin autenticación."""

    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)

    wrapper.__allow_anonymous__ = True
    return wrapper


def authorize(roles: Optional[list[str]] = None):
    """Marca una ruta que requiere autenticación y, opcionalmente, roles."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            principal = principal_ctx.get()
            if principal is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            if roles and not any(r in principal.roles for r in roles):
                raise HTTPException(status_code=403, detail="Forbidden")
            return await func(*args, **kwargs)

        wrapper.__authorize_roles__ = roles or []
        wrapper.__has_authorize__ = True
        return wrapper

    return decorator

security_scheme = HTTPBearer(auto_error=False)

# Rutas de documentación expuestas por FastAPI con GET y HEAD
DOCS_PATHS: set[tuple[str, str]] = {
    ("/openapi.json", "GET"),
    ("/openapi.json", "HEAD"),
    ("/docs", "GET"),
    ("/docs", "HEAD"),
    ("/docs/oauth2-redirect", "GET"),
    ("/docs/oauth2-redirect", "HEAD"),
    ("/redoc", "GET"),
    ("/redoc", "HEAD"),
}


class PrincipalNotSetError(Exception):
    """Excepción lanzada cuando se intenta acceder al Principal pero no está establecido en el contexto."""
    pass

def get_current_principal() -> "Principal":
    """Factory function que obtiene el Principal actual del ContextVar."""
    principal = principal_ctx.get()
    if principal is None:
        raise PrincipalNotSetError("No hay un Principal establecido en el contexto actual")
    return principal


# ============================================================
# Modelos y clases auxiliares
# ============================================================
@component(provider_type=ProviderType.FACTORY,factory=get_current_principal)
class Principal(BaseModel):
    username:str
    roles:List[str]    

@component
class Service:    
    @inject
    def __call__(self, principal:Principal=deps(Principal)):
        print(principal)





class ErrorResponse(BaseModel):
    timestamp:str =  Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec='milliseconds'))
    status: int
    error: str
    exception: Optional[str] = None
    message: Union[str|Sequence[Any]]
    path: str


class SendInterceptor:
    """
    Intercepta respuestas HTTP para reescribir cuerpos de error (>=400) con un JSON uniforme,
    sin violar el orden ASGI. Si es error, NO envía el 'start' original; bufferiza el body y
    después emite un único 'http.response.start' + 'http.response.body' con nuestro JSON.
    """
    def __init__(self, original_send: Send, request_path: str):
        self.original_send = original_send
        self.request_path = request_path
        self.status_code: Optional[int] = None
        self.headers: Dict[bytes, bytes] = {}
        self.body_parts: list[bytes] = []
        self._intercept_error = False  # True si debemos suprimir la respuesta original y enviar la nuestra

    async def send(self, message: Message) -> None:
        msg_type = message["type"]

        if msg_type == "http.response.start":
            # Guardamos status y headers
            self.status_code = message["status"]
            self.headers = dict(message.get("headers", []))

            if self.status_code and self.status_code >= 400:
                # Es error: NO reenviamos este start; esperaremos a tener todo el body
                self._intercept_error = True
                return
            else:
                # No es error: pasamos tal cual
                await self.original_send(message)
                return

        elif msg_type == "http.response.body":
            if self._intercept_error:
                # Bufferizar todo el cuerpo del error original
                body = message.get("body", b"")
                if body:
                    self.body_parts.append(body)

                if not message.get("more_body", False):
                    # Fin del body: construimos nuestra respuesta JSON
                    original_body = b"".join(self.body_parts)
                    error_response = await self._create_custom_error_response(original_body)

                    # Enviamos UN único start + body con nuestro JSON
                    await self.original_send({
                        "type": "http.response.start",
                        "status": self.status_code,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await self.original_send({
                        "type": "http.response.body",
                        "body": error_response.encode(),
                        "more_body": False,
                    })

                    # Reset por seguridad
                    self._intercept_error = False
                    self.body_parts.clear()
                return
            else:
                # No es error: passthrough
                await self.original_send(message)
                return

        # Cualquier otro tipo de mensaje ASGI (poco común en http) se pasa tal cual
        await self.original_send(message)

    async def _create_custom_error_response(self, original_body: bytes) -> str:
        """Crea una respuesta de error personalizada"""
        try:
            original_data = json.loads(original_body.decode()) if original_body else {}
        except Exception:
            original_data = {}

        detail = original_data.get("detail", "Error")

        exception_name = "HTTPException"
        if self.status_code == 403:
            exception_name = "ForbiddenException"
        elif self.status_code == 401:
            exception_name = "UnauthorizedException"
        elif self.status_code == 404:
            exception_name = "NotFoundException"        
        elif self.status_code == 422:
            exception_name = "ValidationException"

        response = ErrorResponse(
            
            status=self.status_code,
            error=self._get_error_name_from_status(self.status_code),
            exception=exception_name,
            message=detail if isinstance(detail, str) else str(detail),
            path=self.request_path
        )

        data = response.model_dump()        
        return json.dumps(data)

    def _get_error_name_from_status(self, status_code: int) -> str:
        status_map = {
            400: "Bad Request Error",
            401: "Unauthorized Error",
            403: "Forbidden Error",
            404: "Not Found Error",
            405: "Method Not Allowed",
            415: "Unsupported Media Type",
            422: "Validation Error",
            500: "Internal Server Error",
        }
        return status_map.get(status_code, f"HTTP {status_code} Error")


def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Maneja las excepciones HTTP y devuelve una respuesta personalizada"""
    response = ErrorResponse(
        
        status=exc.status_code,
        error=f"HTTP {exc.status_code} Error",
        exception="HTTPException",
        message=str(exc.detail),
        path=request.url.path,
    )
    data = response.model_dump()    
    return JSONResponse(status_code=exc.status_code, content=data)


class ErrorHandlerMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        responder = SendInterceptor(send, request.url.path)

        try:
            await self.app(scope, receive, responder.send)

        except HTTPException as exc:
            # Manejamos excepciones que no fueron procesadas por FastAPI
            json_response = handle_http_exception(request, exc)
            await json_response(scope, receive, send)
        except ValidationException as exc:
            response = ErrorResponse(                
                status=422,
                error="Validation Error",
                exception=exc.__class__.__name__,
                message=exc.errors(),
                path=request.url.path,
            )

            data = response.model_dump()            
            json_response = JSONResponse(status_code=422, content=data)
            await json_response(scope, receive, send)

        except Exception as exc:
            # Manejamos excepciones no HTTP
            logger.error(f"Unhandled exception: {exc}", exc_info=True)
            response = ErrorResponse(                
                status=500,
                error="Internal Server Error",
                exception=exc.__class__.__name__,
                message=str(exc),
                path=request.url.path,
            )

            data = response.model_dump()          
            json_response = JSONResponse(status_code=500, content=data)
            await json_response(scope, receive, send)


class AuthMiddleware:
    """Middleware para inyectar el Principal en el contexto."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        method, path = request.method.upper(), request.url.path

        # Comprobar si la ruta existe y si el método es válido
        route_found = False
        allowed_methods = set()

        for route in request.app.router.routes:
            if hasattr(route, "path_regex") and route.path_regex.match(path):
                route_found = True
                allowed_methods.update(route.methods or set())

        # Si no existe la ruta o el método no está permitido → dejar que otro middleware maneje 404/405
        if not route_found or (method not in allowed_methods):
            await self.app(scope, receive, send)
            return

        # Extraer token del header Authorization
        auth_token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ", 1)[1]

        # Autenticar basado en el token
        principal = None
        if auth_token == "admin":
            principal = Principal(username="admin", roles=["admin"])
        elif auth_token == "user":
            principal = Principal(username="user", roles=["user"])

        # Verificar si la ruta requiere autenticación
        route_key = (path, method)
        if (
            route_key not in DOCS_PATHS
            and route_key not in _allow_anonymous_routes
            and principal is None
        ):
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Establecer el principal en el contexto una sola vez
        context_token = principal_ctx.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            # Resetear correctamente el contexto usando el token
            principal_ctx.reset(context_token)


# ============================================================
# OpenAPI personalizado
# ============================================================
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    has_auth_middleware = any(
        hasattr(middleware, 'cls') and middleware.cls is AuthMiddleware
        for middleware in app.user_middleware
    )

    def ensure_validation_schemas():
        """Asegura que ValidationError esté definido."""
        schemas = openapi_schema["components"].setdefault("schemas", {})

        if "ValidationError" not in schemas:
            schemas["ValidationError"] = {
                "type": "object",
                "title": "ValidationError",
                "properties": {
                    "loc": {
                        "type": "array",
                        "items": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "integer"}
                            ]
                        }
                    },
                    "msg": {"type": "string"},
                    "type": {"type": "string"}
                },
                "required": ["loc", "msg", "type"],
                "example": {
                    "loc": ["body", "email"],
                    "msg": "field required",
                    "type": "value_error.missing"
                }
            }

    openapi_schema.setdefault("components", {})

    if has_auth_middleware:
        openapi_schema["components"]["securitySchemes"] = {
            "HTTPBearer": {"type": "http", "scheme": "bearer"}
        }

        ensure_validation_schemas()

        openapi_schema["components"]["schemas"]["ErrorResponse"] = {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string", "format": "date-time"},
                "status": {"type": "integer"},
                "error": {"type": "string"},
                "exception": {"type": "string", "nullable": True},
                "message": {
                    "anyOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/ValidationError"}
                        }
                    ],
                    "description": "Error message - either a simple string or array of validation errors"
                },
                "path": {"type": "string"},
            },
            "required": ["timestamp", "status", "error", "message", "path"]
        }

        error_responses = {
            "UnauthorizedError": {
                "description": "Access token is missing or invalid",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
            },
            "ForbiddenError": {
                "description": "Insufficient permissions",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
            },
            "ValidationError": {
                "description": "Validation error",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
            },
        }
        openapi_schema["components"].setdefault("responses", {}).update(error_responses)

    else:
        ensure_validation_schemas()

        openapi_schema["components"]["schemas"]["ErrorResponse"] = {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string", "format": "date-time"},
                "status": {"type": "integer"},
                "error": {"type": "string"},
                "exception": {"type": "string", "nullable": True},
                "message": {
                    "anyOf": [
                        {"type": "string"},
                        {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/ValidationError"}
                        }
                    ]
                },
                "path": {"type": "string"},
            },
            "required": ["timestamp", "status", "error", "message", "path"]
        }

        if "HTTPValidationError" in openapi_schema["components"]["schemas"]:
            del openapi_schema["components"]["schemas"]["HTTPValidationError"]

        openapi_schema["components"].setdefault("responses", {})["ValidationError"] = {
            "description": "Validation error",
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
        }

    for path, path_item in openapi_schema["paths"].items():
        if any((path, m) in DOCS_PATHS for m in ["GET", "HEAD"]):
            continue
        for method, operation in path_item.items():
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
                route_key = (path, method.upper())
                if "responses" in operation and "422" in operation["responses"]:
                    operation["responses"]["422"] = {"$ref": "#/components/responses/ValidationError"}
                if route_key not in _allow_anonymous_routes and has_auth_middleware:
                    operation["security"] = [{"HTTPBearer": []}]
                    operation.setdefault("responses", {})
                    operation["responses"]["401"] = {"$ref": "#/components/responses/UnauthorizedError"}
                    if route_key in _authorize_routes:
                        operation["responses"]["403"] = {"$ref": "#/components/responses/ForbiddenError"}

    if "components" in openapi_schema and "schemas" in openapi_schema["components"]:
        if "HTTPValidationError" in openapi_schema["components"]["schemas"]:
            del openapi_schema["components"]["schemas"]["HTTPValidationError"]
        
        schemas = openapi_schema["components"]["schemas"]
        reordered = {k: v for k, v in schemas.items()
                     if k not in ("ErrorResponse", "ValidationError")}
        for key in ("ErrorResponse", "ValidationError"):
            if key in schemas:
                reordered[key] = schemas[key]
        openapi_schema["components"]["schemas"] = reordered

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# ============================================================
# Configuración de seguridad automática
# ============================================================
def setup_security_dependencies(app: FastAPI):
    for route in app.routes:
        if isinstance(route, APIRoute):
            endpoint = getattr(route, "endpoint", None)

            if getattr(endpoint, "__allow_anonymous__", False):
                for method in route.methods or []:
                    _allow_anonymous_routes.add((route.path, method.upper()))
                continue

            # Verificar si es una ruta de documentación
            is_docs_route = any(
                (route.path, method.upper()) in DOCS_PATHS
                for method in route.methods or []
            )

            if is_docs_route:
                for method in route.methods or []:
                    _allow_anonymous_routes.add((route.path, method.upper()))
                continue

            if getattr(endpoint, "__has_authorize__", False):
                for method in route.methods or []:
                    _authorize_routes.add((route.path, method.upper()))

            # Verificar dependencias de seguridad existentes
            has_security_dependency = any(
                (
                    hasattr(dep, "dependency")
                    and any(
                        hasattr(p.default, "scheme")
                        and isinstance(getattr(p.default, "scheme", None), HTTPBearer)
                        for p in inspect.signature(dep.dependency).parameters.values()
                        if hasattr(p, "default") and p.default is not inspect.Parameter.empty
                    )
                )
                or (hasattr(dep, "scheme") and isinstance(getattr(dep, "scheme", None), HTTPBearer))
                for dep in route.dependencies
            )

            if not has_security_dependency:
                route.dependencies.append(Security(security_scheme))




#=============================================================
# Genera los códigos de error de la app para integrarlos en openapi
#=============================================================
def build_error_responses(*codes: int) -> Dict[int, dict]:
    """Genera un diccionario de responses para FastAPI
    solo aceptando 400, 404 y 409.
    """
    allowed_codes = {
        400: "Bad Request",
        404: "Not Found",
        409: "Conflict",
    }

    result = {}
    for code in codes:
        if code not in allowed_codes:
            raise ValueError(
                f"Código {code} no permitido. Solo 400, 404 o 409."
            )
        result[code] = {
            "description": allowed_codes[code],
            "model": ErrorResponse
        }
    return result


# ============================================================
# App y endpoints de ejemplo
# ============================================================

app.openapi = custom_openapi

# Agregar middlewares en el orden correcto
app.add_middleware(AuthMiddleware)
app.add_middleware(ErrorHandlerMiddleware)


class Request1(BaseModel):
    id: int


class Response1(BaseModel):
    id: int






@app.post("/public", 
          summary="El perro de San Roque no tiene Rabo",   
          responses=  build_error_responses(400,409)     
)
@allow_anonymous
async def public_endpoint(req: Request1) -> Response1:
    return Response1(id=req.id)


@app.get("/private")
async def private_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Hola {principal.username}"}


@app.get("/admin")
@authorize(["admin"])
@inject
#service: Service = deps(Service)
async def admin_endpoint(service:Service=deps(Service)):
    service()
    return {"message": "Zona admin"}


@app.get("/another-private")
async def another_private_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Otra ruta privada para {principal.username}"}


@app.get("/user-only")
@authorize(["user", "admin"])
async def user_only_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Solo usuarios y admins: {principal.username}"}


@app.post("/create-something")
async def create_something():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Algo creado por {principal.username}"}


@app.get("/manual-security", dependencies=[Security(security_scheme)])
async def manual_security_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Ruta con seguridad manual para {principal.username}"}


# Limpiar exception handlers por defecto para usar nuestro middleware
app.exception_handlers.clear()


if __name__ == "__main__":    
    import uvicorn
    uvicorn.run("authorization:app", host="0.0.0.0", port=8081, reload=True)
