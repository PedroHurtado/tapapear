import functools
import inspect
import httpx
import re
from contextvars import ContextVar
from typing import (
    Any,
    Callable,
    Optional,
    get_origin,
    get_args,
    Type,
    Dict,
    List,
)
from pydantic import BaseModel, create_model, ValidationError
from dataclasses import dataclass
from enum import Enum


class File(BaseModel):
    content: bytes
    filename: Optional[str] = None
    content_type: Optional[str] = None


jwt_token_var: ContextVar[Optional[str]] = ContextVar("jwt_token", default=None)


class RequestType(Enum):
    QUERY = "query"
    BODY = "body"
    FORM = "form"
    FORM_DATA = "form_data"


@dataclass
class CompiledRequest:
    """Estructura compilada para optimizar las requests"""

    param_model: Type[BaseModel]
    path_params: List[str]
    request_type: Optional[RequestType]
    return_type: Type
    is_return_list: bool
    is_return_file: bool
    has_files_in_form: bool
    has_files_in_body: bool
    body_file_field: Optional[str]


class ContextAuth(httpx.Auth):
    """Auth que obtiene el JWT desde un contextvar y lo añade al header Authorization."""

    def auth_flow(self, request: httpx.Request):
        if token := jwt_token_var.get():
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
        self._compiled_cache: Dict[str, CompiledRequest] = {}

    def _is_file_type(self, annotation) -> bool:
        """Detecta si una anotación es de tipo File"""
        match annotation:
            case _ if annotation is File:
                return True
            case _ if get_origin(annotation) is list:
                args = get_args(annotation)
                return len(args) == 1 and args[0] is File
            case _:
                return False

    def _has_file_fields(self, model_class: Type[BaseModel]) -> bool:
        """Comprueba si un modelo Pydantic contiene campos de tipo File"""
        return any(
            self._is_file_type(field.annotation)
            for field in model_class.model_fields.values()
        )

    def _extract_path_params(self, path: str) -> List[str]:
        """Extrae los parámetros de la ruta"""
        return re.findall(r"\{([^}]+)\}", path)

    def _compile_request(self, func: Callable, path: str) -> CompiledRequest:
        """Compila la información del request una sola vez"""
        sig = inspect.signature(func)
        fields = {}
        path_params = self._extract_path_params(path)

        request_type, has_files_in_form, has_files_in_body, body_file_field = (
            self._detect_request_info(sig)
        )

        for name, param in sig.parameters.items():
            if name == "self":
                continue
            annotation = param.annotation
            default = param.default if param.default is not inspect._empty else ...
            fields[name] = (annotation, default)

        param_model = create_model(f"{func.__name__}Params", **fields)

        actual_return_type, is_return_list, is_return_file = self._detect_return_type(
            sig.return_annotation
        )

        return CompiledRequest(
            param_model,
            path_params,
            request_type,
            actual_return_type,
            is_return_list,
            is_return_file,
            has_files_in_form,
            has_files_in_body,
            body_file_field,
        )

    def _detect_request_info(self, sig: inspect.Signature):
        """Detecta el tipo de request y si contiene archivos"""
        request_type = None
        has_files_in_form = has_files_in_body = False
        body_file_field = None

        for name, param in sig.parameters.items():
            if name == "self":
                continue
            annotation = param.annotation

            match name:
                case "query" | "body" | "form" | "form_data":
                    request_type = RequestType(name)
                    if name in {"form", "form_data"} and hasattr(
                        annotation, "model_fields"
                    ):
                        has_files_in_form = self._has_file_fields(annotation)
                    elif name == "body" and hasattr(annotation, "model_fields"):
                        has_files_in_body = self._has_file_fields(annotation)
                        if has_files_in_body:
                            for (
                                field_name,
                                field_info,
                            ) in annotation.model_fields.items():
                                if self._is_file_type(field_info.annotation):
                                    body_file_field = field_name
                                    if field_info.annotation is File:
                                        break
                case _:
                    pass
        return request_type, has_files_in_form, has_files_in_body, body_file_field

    def _detect_return_type(self, return_annotation):
        """Detecta tipo de retorno y si es lista o archivo"""
        if return_annotation == inspect.Signature.empty:
            return return_annotation, False, False

        origin = get_origin(return_annotation)
        args = get_args(return_annotation)
        is_return_list, actual_return_type = False, return_annotation

        match origin:
            case _ if origin is list and args:
                is_return_list = True
                actual_return_type = args[0]
            case _:
                pass

        return actual_return_type, is_return_list, actual_return_type is File

    async def _send_request(
        self,
        method: str,
        path: str,
        compiled_req: CompiledRequest,
        args,
        kwargs,
        allow_anonymous: bool = False,
        decorator_headers: Optional[Dict] = None,
    ) -> Any:

        request = self._build_request(
            method, path, compiled_req, args, kwargs, allow_anonymous, decorator_headers
        )

        method, url = request.pop("method"), request.pop("url")

        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, **request)
            response.raise_for_status()

        return self._parse_response(response, compiled_req)

    def _build_request(
        self,
        method: str,
        path: str,
        compiled_req: CompiledRequest,
        args,
        kwargs,
        allow_anonymous: bool = False,
        decorator_headers: Optional[Dict] = None,
    ):
        validated = self._validate_args(compiled_req, args, kwargs)

        # Path params
        url_params = {
            p: getattr(validated, p)
            for p in compiled_req.path_params
            if hasattr(validated, p)
        }
        url = f"{self.base_url}{path.format(**url_params)}"

        # Headers combinados
        combined_headers = {**self.headers, **(decorator_headers or {})}

        # Construcción según tipo de request
        query = json_body = form_data = files = content = None

        match compiled_req.request_type:
            case RequestType.QUERY:
                query = self._build_query_request(validated)

            case RequestType.BODY:
                json_body, content, combined_headers = self._build_body_request(
                    validated, compiled_req, combined_headers
                )

            case RequestType.FORM:
                form_data, files = self._build_form_request(validated, compiled_req)

            case RequestType.FORM_DATA:
                form_data, files = self._build_form_data_request(validated)

            case _:
                pass

        return {
            "method": method,
            "url": url,
            "auth": None if allow_anonymous else self.auth,
            "headers": combined_headers,
            "params": query,
            "json": json_body,
            "data": form_data,
            "files": files,
            "content": content,
        }

    def _validate_args(self, compiled_req: CompiledRequest, args, kwargs):
        """Valida los argumentos contra el modelo Pydantic"""
        bound_args = {}
        if args:
            param_names = list(compiled_req.param_model.model_fields.keys())
            for i, arg in enumerate(args[1:]):  # saltar self
                if i < len(param_names):
                    bound_args[param_names[i]] = arg
        bound_args.update(kwargs)

        try:
            return compiled_req.param_model(**bound_args)
        except ValidationError as e:
            func_name = getattr(args[0], "__class__", {}).get("__name__", "unknown")
            raise ValueError(f"Invalid arguments for {func_name}: {e}") from e

    def _build_query_request(self, validated):
        query_obj = getattr(validated, "query", None)
        if query_obj is None:
            return None
        return query_obj.model_dump() if isinstance(query_obj, BaseModel) else query_obj

    def _build_body_request(self, validated, compiled_req, headers: Dict):
        body_obj = getattr(validated, "body", None)
        if body_obj is None:
            return None, None, headers

        if compiled_req.has_files_in_body and compiled_req.body_file_field:
            file_data = getattr(body_obj, compiled_req.body_file_field)
            if isinstance(file_data, list):
                content = b"".join(f.content for f in file_data)
                if (
                    not headers.get("Content-Type")
                    and file_data
                    and file_data[0].content_type
                ):
                    headers["Content-Type"] = file_data[0].content_type
            else:
                content = file_data.content
                if not headers.get("Content-Type") and file_data.content_type:
                    headers["Content-Type"] = file_data.content_type
            return None, content, headers
        return body_obj.model_dump(), None, headers

    def _build_form_request(self, validated, compiled_req):
        form_obj = getattr(validated, "form", None)
        if form_obj is None:
            return None, None
        if compiled_req.has_files_in_form:
            return self._prepare_files_data(form_obj)
        return form_obj.model_dump(), None

    def _build_form_data_request(self, validated):
        form_data_obj = getattr(validated, "form_data", None)
        if form_data_obj is None:
            return None, None
        return self._prepare_files_data(form_data_obj)

    def _parse_response(self, response: httpx.Response, compiled_req: CompiledRequest):
        """Parsea la respuesta según las especificaciones"""
        if response.status_code == 204:
            return ""

        content_type = response.headers.get("content-type", "").lower()

        # Caso File
        if compiled_req.is_return_file:
            filename = "upload"
            if "filename=" in (cd := response.headers.get("content-disposition", "")):
                filename = cd.split("filename=")[1].strip('"')
            return File.model_validate(
                {
                    "content": response.content,
                    "filename": filename,
                    "content_type": content_type or "application/octet-stream",
                }
            )

        # Caso JSON o fallback
        try:
            data = response.json()
        except ValueError:
            data = response.text

        if compiled_req.return_type == inspect.Signature.empty:
            return data

        if compiled_req.is_return_list:
            return (
                []
                if data is None
                else [
                    self._parse_model(compiled_req.return_type, item) for item in data
                ]
            )

        return self._parse_model(compiled_req.return_type, data)

    def _parse_model(self, typ: Type, data: Any):
        return (
            typ.model_validate(data)
            if inspect.isclass(typ) and issubclass(typ, BaseModel)
            else data
        )

    def _decorator(
        self,
        method: str,
        path: str,
        allow_anonymous: bool = False,
        headers: Optional[Dict] = None,
    ) -> Callable:
        def wrapper(func: Callable) -> Callable:
            cache_key = f"{func.__module__}.{func.__qualname__}"
            compiled_req = self._compiled_cache.get(cache_key) or self._compile_request(
                func, path
            )
            self._compiled_cache[cache_key] = compiled_req

            @functools.wraps(func)
            async def inner(*args, **kwargs) -> Any:
                return await self._send_request(
                    method,
                    path,
                    compiled_req,
                    args,
                    kwargs,
                    allow_anonymous,
                    headers or {},
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
