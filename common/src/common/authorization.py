from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import HTTPBearer
from fastapi.routing import APIRoute
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from contextvars import ContextVar
from contextlib import asynccontextmanager
from typing import Optional, Callable
from functools import wraps
import inspect
from starlette.types import ASGIApp, Receive, Scope, Send

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
            if roles and not any(r in principal.roles for r in roles):
                raise HTTPException(status_code=403, detail="Forbidden")
            return await func(*args, **kwargs)

        wrapper.__authorize_roles__ = roles or []
        wrapper.__has_authorize__ = True
        return wrapper

    return decorator


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

        token = request.headers.get("Authorization")
        principal = None
        if token == "Bearer admin":
            principal = Principal("admin", ["admin"])
        elif token == "Bearer user":
            principal = Principal("user", ["user"])
        principal_ctx.set(principal)

        if (
            (path, method) not in DOCS_PATHS
            and (method, path) not in _allow_anonymous_routes
            and principal is None
        ):
            raise HTTPException(status_code=401, detail="Not authenticated")

        await self.app(scope, receive, send)


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

    has_auth_middleware = any(m.cls is AuthMiddleware for m in app.user_middleware)

    if has_auth_middleware:
        openapi_schema.setdefault("components", {})
        openapi_schema["components"]["securitySchemes"] = {
            "HTTPBearer": {"type": "http", "scheme": "bearer"}
        }

        error_responses = {
            "UnauthorizedError": {
                "description": "Access token is missing or invalid",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "detail": {
                                    "type": "string",
                                    "example": "Not authenticated",
                                }
                            },
                        }
                    }
                },
            },
            "ForbiddenError": {
                "description": "Insufficient permissions",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "detail": {"type": "string", "example": "Forbidden"}
                            },
                        }
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
                route_key = (method.upper(), path)

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
                    _allow_anonymous_routes.add((method.upper(), route.path))
                continue

            if any(
                (route.path, method.upper()) in DOCS_PATHS
                for method in route.methods or []
            ):
                for method in route.methods or []:
                    _allow_anonymous_routes.add((method.upper(), route.path))
                continue

            if getattr(endpoint, "__has_authorize__", False):
                for method in route.methods or []:
                    _authorize_routes.add((method.upper(), route.path))

            has_security_dependency = any(
                (
                    hasattr(dep, "dependency")
                    and any(
                        hasattr(p.default, "scheme")
                        and isinstance(p.default.scheme, HTTPBearer)
                        for p in inspect.signature(dep.dependency).parameters.values()
                    )
                )
                or (hasattr(dep, "scheme") and isinstance(dep.scheme, HTTPBearer))
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
app.add_middleware(AuthMiddleware)


class Request1(BaseModel):
    id: str


class Response1(BaseModel):
    id: str


@app.get("/public", summary="El perro de San Roque no tiene Rabo")
@allow_anonymous
async def public_endpoint(req: Request1) -> Response1:
    return Response1(id=req.id)


@app.get("/private")
async def private_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Hola {principal.username}"}


@app.get("/admin")
@authorize(["admin"])
async def admin_endpoint():
    return {"message": "Zona admin"}


@app.get("/another-private")
async def another_private_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Otra ruta privada para {principal.username}"}


@app.get("/user-only")
@authorize(["user", "admin"])
async def user_only_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Solo usuarios y admins: {principal.username}"}


@app.post("/create-something")
async def create_something():
    principal = principal_ctx.get()
    return {"message": f"Algo creado por {principal.username}"}


@app.get("/manual-security", dependencies=[Security(security_scheme)])
async def manual_security_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Ruta con seguridad manual para {principal.username}"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
