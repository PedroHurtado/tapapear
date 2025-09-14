from typing import Callable, Optional, List
from functools import wraps
from fastapi import HTTPException,Security, FastAPI
from fastapi.routing import APIRoute
from fastapi.security import HTTPBearer
from contextvars import ContextVar

from pydantic import BaseModel
from common.ioc import component, ProviderType
from common.context import context
from common.util import ID
import inspect

security_scheme = HTTPBearer(auto_error=False)

principal_ctx: ContextVar[Optional["Principal"]] = ContextVar("principal", default=None)




def get_current_principal() -> "Principal":    
    return principal_ctx.get()    


@component(provider_type=ProviderType.FACTORY,factory=get_current_principal)
class Principal(BaseModel):
    id:ID
    username:str
    email:str
    role:str    
    tenant:Optional[ID] = None




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

def setup_security_dependencies(app: FastAPI):       
    for route in app.routes:
        if isinstance(route, APIRoute):
            endpoint = getattr(route, "endpoint", None)

            if getattr(endpoint, "__allow_anonymous__", False):
                for method in route.methods or []:
                    context.allow_anonymous_routes.add((route.path, method.upper()))
                continue

            # Verificar si es una ruta de documentación
            is_docs_route = any(
                (route.path, method.upper()) in context.docs_path
                for method in route.methods or []
            )

            if is_docs_route:
                for method in route.methods or []:
                    context.allow_anonymous_routes.add((route.path, method.upper()))
                continue

            if getattr(endpoint, "__has_authorize__", False):
                for method in route.methods or []:
                    context.authorize_routes.add((route.path, method.upper()))

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
