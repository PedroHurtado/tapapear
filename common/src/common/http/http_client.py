import functools
import inspect
import httpx

from contextvars import ContextVar
from typing import Any, Callable, Optional, get_origin, get_args, Type, Dict
from pydantic import BaseModel, create_model, ValidationError


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


class HttpClient:
    def __init__(
        self,
        base_url: str,
        auth: Optional[httpx.Auth] = ContextAuth(),
        headers: Optional[Dict] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.headers = headers or {}

    async def _build_request(
        self,
        method: str,
        path: str,
        func: Callable,
        args,
        kwargs,
        allow_anonymous: bool = False,
        decorator_headers: Optional[Dict] = None,
    ):
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        bound.apply_defaults()

        # --- validar args con Pydantic ---
        fields = {
            name: (
                param.annotation,
                param.default if param.default is not inspect._empty else ...,
            )
            for name, param in sig.parameters.items()
        }
        Model = create_model(f"{func.__name__}Params", **fields)  # modelo dinámico
        try:
            validated = Model(**bound.arguments)
        except ValidationError as e:
            raise ValueError(f"Invalid arguments for {func.__name__}: {e}") from e

        # --- Path params ---
        url = f"{self.base_url}{path.format(**validated.model_dump())}"

        # --- Query & Body ---
        query = None
        body = None
        if "query" in validated.model_fields_set:
            q = getattr(validated, "query")
            if q is not None:
                query = q.model_dump() if isinstance(q, BaseModel) else q
        if "body" in validated.model_fields_set:
            b = getattr(validated, "body")
            if b is not None:
                body = b.model_dump() if isinstance(b, BaseModel) else b

        # --- Combinar headers ---
        combined_headers = {**self.headers}  # Empezar con headers de la clase
        if decorator_headers:
            combined_headers.update(decorator_headers)  # Agregar headers del decorador

        # --- Determinar auth ---
        auth_to_use = None if allow_anonymous else self.auth

        async with httpx.AsyncClient(
            auth=auth_to_use, headers=combined_headers
        ) as client:
            response = await client.request(method, url, params=query, json=body)
            response.raise_for_status()

        return self._parse_response(response, func)

    def _parse_response(self, response: httpx.Response, func: Callable):
        return_type = inspect.signature(func).return_annotation

        if response.status_code == 204:  # No Content
            return None

        data = response.json()

        # No return annotation → raw json
        if return_type is inspect.Signature.empty:
            return data

        origin = get_origin(return_type)
        args = get_args(return_type)

        # Optional[T]
        if origin is Optional and args:
            inner = args[0]
            if data is None:
                return None
            return self._parse_model(inner, data)

        # List[T] or Optional[List[T]]
        if origin is list or (origin is Optional and get_origin(args[0]) is list):
            inner = args[0] if origin is list else get_args(args[0])[0]
            if data is None:
                return None
            return [self._parse_model(inner, item) for item in data]

        return self._parse_model(return_type, data)

    def _parse_model(self, typ: Type, data: Any):
        if inspect.isclass(typ) and issubclass(typ, BaseModel):
            return typ.model_validate(data)
        return data

    def _decorator(
        self,
        method: str,
        path: str,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ) -> Callable:
        def wrapper(func: Callable) -> Callable:
            @functools.wraps(func)
            async def inner(*args, **kwargs) -> Any:
                return await self._build_request(
                    method, path, func, args, kwargs, allow_anonymous, headers or {}
                )

            return inner

        return wrapper

    # Decoradores HTTP
    def get(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ):
        return self._decorator("GET", path, allow_anonymous, headers)

    def post(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ):
        return self._decorator("POST", path, allow_anonymous, headers)

    def put(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ):
        return self._decorator("PUT", path, allow_anonymous, headers)

    def delete(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ):
        return self._decorator("DELETE", path, allow_anonymous, headers)

    def patch(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ):
        return self._decorator("PATCH", path, allow_anonymous, headers)
