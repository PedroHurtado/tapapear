import inspect
from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import HTTPBearer
from fastapi.routing import APIRoute
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from pydantic import BaseModel
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Dict, Optional, Callable, Any
from functools import wraps

from starlette.types import ASGIApp, Receive, Scope, Send, Message
from datetime import datetime, timezone
import json
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# Constantes y estado global
# ============================================================
principal_ctx: ContextVar[Optional["Principal"]] = ContextVar("principal", default=None)
_allow_anonymous_routes: set[tuple[str, str]] = set()
_authorize_routes: set[tuple[str, str]] = set()

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


# ============================================================
# Modelos y clases auxiliares
# ============================================================
class Principal:
    def __init__(self, username: str, roles: list[str]):
        self.username = username
        self.roles = roles


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


class ErrorResponse(BaseModel):
    timestamp: datetime
    status: int
    error: str
    exception: Optional[str] = None
    message: str
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
            timestamp=datetime.now(timezone.utc),
            status=self.status_code,
            error=self._get_error_name_from_status(self.status_code),
            exception=exception_name,
            message=detail if isinstance(detail, str) else str(detail),
            path=self.request_path
        )

        data = response.model_dump()
        data['timestamp'] = data['timestamp'].isoformat(timespec='milliseconds')
        return json.dumps(data)

    def _get_error_name_from_status(self, status_code: int) -> str:
        status_map = {
            400: "Bad Request Error",
            401: "Unauthorized Error",
            403: "Forbidden Error",
            404: "Not Found Error",
            422: "Validation Error",
            500: "Internal Server Error",
        }
        return status_map.get(status_code, f"HTTP {status_code} Error")


def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Maneja las excepciones HTTP y devuelve una respuesta personalizada"""
    response = ErrorResponse(
        timestamp=datetime.now(timezone.utc),
        status=exc.status_code,
        error=f"HTTP {exc.status_code} Error",
        exception="HTTPException",
        message=str(exc.detail),
        path=request.url.path,
    )
    data = response.model_dump()
    data['timestamp'] = data['timestamp'].isoformat(timespec='milliseconds')
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

        except Exception as exc:
            # Manejamos excepciones no HTTP
            logger.error(f"Unhandled exception: {exc}", exc_info=True)
            response = ErrorResponse(
                timestamp=datetime.now(timezone.utc),
                status=500,
                error="Internal Server Error",
                exception=exc.__class__.__name__,
                message=str(exc),
                path=request.url.path,
            )

            data = response.model_dump()
            data['timestamp'] = data['timestamp'].isoformat(timespec='milliseconds')

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

        # Extraer token del header Authorization
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

        # Autenticar basado en el token
        principal = None
        if token == "admin":
            principal = Principal("admin", ["admin"])
        elif token == "user":
            principal = Principal("user", ["user"])

        principal_ctx.set(principal)

        # Verificar si la ruta requiere autenticación
        route_key = (path, method)
        if (
            route_key not in DOCS_PATHS
            and route_key not in _allow_anonymous_routes
            and principal is None
        ):
            error_response = ErrorResponse(
                timestamp=datetime.now(timezone.utc),
                status=401,
                error="Unauthorized Error",
                exception="HTTPException",
                message="Not authenticated",
                path=path,
            )

            data = error_response.model_dump()
            data['timestamp'] = data['timestamp'].isoformat(timespec='milliseconds')

            response = JSONResponse(status_code=401, content=data)
            await response(scope, receive, send)
            return

        # Establecer el principal en el contexto antes de continuar
        token = principal_ctx.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            # Limpiar el contexto
            principal_ctx.set(None)


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

    # Verificar si hay middleware de autenticación
    has_auth_middleware = any(
        hasattr(middleware, 'cls') and middleware.cls is AuthMiddleware
        for middleware in app.user_middleware
    )

    if has_auth_middleware:
        openapi_schema.setdefault("components", {})

        # Security
        openapi_schema["components"]["securitySchemes"] = {
            "HTTPBearer": {"type": "http", "scheme": "bearer"}
        }

        # Schema común para errores
        openapi_schema["components"].setdefault("schemas", {})["ErrorResponse"] = {
            "type": "object",
            "properties": {
                "timestamp": {"type": "string"},
                "status": {"type": "integer"},
                "error": {"type": "string"},
                "exception": {"type": "string"},
                "message": {"type": "string"},
                "path": {"type": "string"},
            },
        }

        # Respuestas de error usando el schema
        error_responses = {
            "UnauthorizedError": {
                "description": "Access token is missing or invalid",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
            "ForbiddenError": {
                "description": "Insufficient permissions",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                    }
                },
            },
        }
        openapi_schema["components"].setdefault("responses", {}).update(error_responses)

    for path, path_item in openapi_schema["paths"].items():
        if any((path, m) in DOCS_PATHS for m in ["GET", "HEAD"]):
            continue

        for method, operation in path_item.items():
            if method.upper() in {
                "GET",
                "POST",
                "PUT",
                "DELETE",
                "PATCH",
                "OPTIONS",
                "HEAD",
            }:
                route_key = (path, method.upper())

                if route_key not in _allow_anonymous_routes and has_auth_middleware:
                    operation["security"] = [{"HTTPBearer": []}]
                    operation.setdefault("responses", {})
                    operation["responses"]["401"] = {
                        "$ref": "#/components/responses/UnauthorizedError"
                    }

                    if route_key in _authorize_routes:
                        operation["responses"]["403"] = {
                            "$ref": "#/components/responses/ForbiddenError"
                        }

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


# ============================================================
# Ciclo de vida
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    
    setup_security_dependencies(app)
    _allow_anonymous_routes.update(DOCS_PATHS) 

    yield

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
app = FastAPI(
    lifespan=lifespan,
    title="Mi API con Auth",
    description="Ejemplo con autenticación automática",
    version="1.0.0",
)
app.openapi = custom_openapi

# Agregar middlewares en el orden correcto
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(AuthMiddleware)

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
async def admin_endpoint():
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
