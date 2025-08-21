from starlette.types import ASGIApp,Scope,Receive,Send
from fastapi import Request, HTTPException
from common.security import Principal,principal_ctx
from common.context import context
from common.htto import jwt_token_var

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
            route_key not in context.docs_path
            and route_key not in context.allow_anonymous_routes
            and principal is None
        ):
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Establecer el principal en el contexto una sola vez
        context_token = principal_ctx.set(principal)
        jwt_token = jwt_token_var.set(auth_token)
        try:
            await self.app(scope, receive, send)
        finally:            
            principal_ctx.reset(context_token)
            jwt_token_var.reset(jwt_token)
