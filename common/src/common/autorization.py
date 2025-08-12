from fastapi import FastAPI, Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextvars import ContextVar
from typing import Optional, Callable
from functools import wraps
from contextlib import asynccontextmanager

principal_ctx: ContextVar[Optional["Principal"]] = ContextVar("principal", default=None)
_allow_anonymous_routes: set[tuple[str, str]] = set()

security_scheme = HTTPBearer(auto_error=False)  # No error automático, dejamos que el middleware lo maneje

class Principal:
    def __init__(self, username: str, roles: list[str]):
        self.username = username
        self.roles = roles

def allow_anonymous(func: Callable):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)
    wrapper.__allow_anonymous__ = True
    return wrapper

def authorize(roles: Optional[list[str]] = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            principal = principal_ctx.get()
            if roles and not any(r in principal.roles for r in roles):
                raise HTTPException(status_code=403, detail="Forbidden")
            return await func(*args, **kwargs)
        return wrapper
    return decorator

async def auth_middleware(request: Request, call_next):
    method, path = request.method.upper(), request.url.path

    token = request.headers.get("Authorization")
    principal = None
    if token == "Bearer admin":
        principal = Principal("admin", ["admin"])
    elif token == "Bearer user":
        principal = Principal("user", ["user"])
    principal_ctx.set(principal)

    if (method, path) not in _allow_anonymous_routes and principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return await call_next(request)

@asynccontextmanager
async def lifespan(app: FastAPI):
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if getattr(endpoint, "__allow_anonymous__", False):
            for m in route.methods or []:
                _allow_anonymous_routes.add((m.upper(), route.path))

    docs_paths = [
        ("/openapi.json", "GET"),
        ("/docs", "GET"),
        ("/docs/oauth2-redirect", "GET"),
        ("/redoc", "GET"),
    ]
    for path, method in docs_paths:
        _allow_anonymous_routes.add((method, path))

    print("AllowAnonymous registrados:", _allow_anonymous_routes)
    yield

app = FastAPI(
    lifespan=lifespan,
    title="Mi API con Auth",
    description="Ejemplo con autenticación tipo .NET [Authorize] y [AllowAnonymous]",
    version="1.0.0"
)
app.middleware("http")(auth_middleware)

@app.get("/public")
@allow_anonymous
async def public_endpoint():
    return {"message": "Cualquiera puede acceder"}

@app.get("/private", dependencies=[Security(security_scheme)])
async def private_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Hola {principal.username}"}

@app.get("/admin", dependencies=[Security(security_scheme)])
@authorize(["admin"])
async def admin_endpoint():
    return {"message": "Zona admin"}



import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8081)
