import functools
import inspect
import httpx
from urllib.parse import parse_qs

from contextvars import ContextVar
from typing import Any, Callable, Optional, get_origin, get_args, Type, Dict, Annotated
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

    def _is_file_field(self, field_info) -> bool:
        """Detecta si un campo es un archivo basándose en Annotated[bytes, "file"]"""
        annotation = field_info.annotation
        origin = get_origin(annotation)
        if origin is Annotated:
            args = get_args(annotation)
            return len(args) >= 2 and args[1] == "file"
        return False

    def _prepare_form_data(self, form_model: BaseModel):
        """Separa los datos de form en data (texto) y files (archivos)"""
        form_dict = form_model.model_dump()
        data = {}
        files = {}

        for field_name, field_info in form_model.model_fields.items():
            field_value = form_dict.get(field_name)

            if field_value is None:
                continue

            if self._is_file_field(field_info):
                files[field_name] = field_value
            else:
                data[field_name] = field_value

        return (data if data else None), (files if files else None)

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

        # --- Query, Body, Form & Form Data ---
        query = None
        body = None
        data = None
        files = None

        if "query" in validated.model_fields_set:
            q = getattr(validated, "query")
            if q is not None:
                query = q.model_dump() if isinstance(q, BaseModel) else q

        if "body" in validated.model_fields_set:
            b = getattr(validated, "body")
            if b is not None:
                body = b.model_dump() if isinstance(b, BaseModel) else b

        if "form" in validated.model_fields_set:
            f = getattr(validated, "form")
            if f is not None:
                data = f.model_dump() if isinstance(f, BaseModel) else f

        if "form_data" in validated.model_fields_set:
            fd = getattr(validated, "form_data")
            if fd is not None:
                data, files = self._prepare_form_data(fd)

        # --- Combinar headers ---
        combined_headers = {**self.headers}  # Empezar con headers de la clase
        if decorator_headers:
            combined_headers.update(decorator_headers)  # Agregar headers del decorador

        # --- Determinar auth ---
        auth_to_use = None if allow_anonymous else self.auth

        async with httpx.AsyncClient(
            auth=auth_to_use, headers=combined_headers
        ) as client:
            response = await client.request(
                method, url, params=query, json=body, data=data, files=files
            )
            response.raise_for_status()

        return self._parse_response(response, func)

    def _parse_response(self, response: httpx.Response, func: Callable):
        return_type = inspect.signature(func).return_annotation

        if response.status_code == 204:  # No Content
            return ""

        content_type = response.headers.get("content-type", "").lower()

        # Parsing según Content-Type
        if "application/json" in content_type:
            data = response.json()
        elif "application/x-www-form-urlencoded" in content_type:
            # Parse form urlencoded response
            parsed = parse_qs(response.text)
            # Convertir listas de un elemento a valores únicos
            data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        elif "multipart/form-data" in content_type:
            # Para multipart en respuestas, httpx no tiene parser built-in
            # Tendríamos que usar una librería como python-multipart
            # Por ahora retornamos el texto raw
            data = response.text
        else:
            # Default: tratar como JSON
            try:
                data = response.json()
            except:
                data = response.text

        # No return annotation → raw data
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
