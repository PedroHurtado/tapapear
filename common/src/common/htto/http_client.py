from typing import Optional
from contextvars import ContextVar
import httpx

jwt_token_var: ContextVar[Optional[str]] = ContextVar("jwt_token", default=None)

class ContextAuth(httpx.Auth):
    """
    Auth class que obtiene el JWT desde un contextvar y lo añade al header Authorization.
    """

    def auth_flow(self, request: httpx.Request):
        token = jwt_token_var.get()
        if token:
            request.headers["Authorization"] = f"Bearer {token}"
        yield request