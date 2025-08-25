import functools
import inspect
import httpx
import re
import asyncio
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
    Tuple,
    Set,
)
from pydantic import BaseModel, create_model, ValidationError
from dataclasses import dataclass
from enum import Enum


class HTTPRetryError(Exception):
    def __init__(
        self,
        message: str,
        cause: Exception,
        attempts: int,
        url: str,
        status_code: Optional[int],
    ):
        super().__init__(message)
        self.cause = cause
        self.attempts = attempts
        self.status_code = status_code
        self.url = url


jwt_token_var: ContextVar[Optional[str]] = ContextVar("jwt_token", default=None)


class ContextAuth(httpx.Auth):
    """Auth que obtiene el JWT desde un contextvar y lo añade al header Authorization."""

    def auth_flow(self, request: httpx.Request):
        if token := jwt_token_var.get():
            request.headers["Authorization"] = f"Bearer {token}"
        yield request


class File(BaseModel):
    content: bytes
    filename: Optional[str] = None
    content_type: Optional[str] = None


class RequestType(Enum):
    BODY = "body"
    FORM = "form"
    FORM_DATA = "form_data"


@dataclass
class CompiledRequest:
    """Estructura compilada para optimizar las requests"""

    param_model: Type[BaseModel]
    path_params: List[str]
    request_type: Optional[RequestType]
    has_query: bool
    return_type: Type
    is_return_list: bool
    is_return_file: bool
    has_files_in_form: bool
    has_files_in_body: bool
    body_file_field: Optional[str]


class TypeInspector:
    """Responsable de la inspección de tipos y anotaciones"""

    @staticmethod
    def is_file_type(annotation: Any) -> bool:
        """Detecta si una anotación es de tipo File o List[File]."""
        match annotation:
            case _ if annotation is File:
                return True
            case _ if get_origin(annotation) is list:
                args = get_args(annotation)
                return len(args) == 1 and args[0] is File
            case _:
                return False

    @staticmethod
    def has_file_fields(model_class: Type[BaseModel]) -> bool:
        """Comprueba si un modelo Pydantic contiene campos de tipo File"""
        return any(
            TypeInspector.is_file_type(field.annotation)
            for field in model_class.model_fields.values()
        )

    @staticmethod
    def detect_return_type(return_annotation: Any) -> Tuple[Any, bool, bool]:
        """Detecta tipo de retorno y si es lista o archivo"""
        if return_annotation == inspect.Signature.empty:
            return return_annotation, False, False

        origin = get_origin(return_annotation)
        args = get_args(return_annotation)
        is_return_list = False
        actual_return_type = return_annotation

        if origin is list and args:
            is_return_list = True
            actual_return_type = args[0]

        # is_return_file solo cuando NO es lista y el tipo es File
        is_return_file = (not is_return_list) and (actual_return_type is File)
        return actual_return_type, is_return_list, is_return_file


class RequestTypeDetector:
    """Responsable de detectar el tipo de request y validaciones"""

    SPECIAL_PARAMS: Set[str] = {"body", "form", "form_data"}

    def __init__(self, type_inspector: TypeInspector):
        self.type_inspector = type_inspector

    def detect_request_info(
        self, sig: inspect.Signature
    ) -> Tuple[Optional[RequestType], bool, bool, bool, Optional[str]]:
        """Detecta el tipo de request, si tiene query y si contiene archivos"""
        request_type: Optional[RequestType] = None
        has_files_in_form = has_files_in_body = has_query = False
        body_file_field: Optional[str] = None

        # Validar que solo hay un tipo de request (body, form, form_data)
        used_specials = [
            name for name in sig.parameters.keys() if name in self.SPECIAL_PARAMS
        ]

        if len(used_specials) > 1:
            raise ValueError(
                f"No se puede combinar más de un tipo de request entre body, form y form_data: {used_specials}"
            )

        for name, param in sig.parameters.items():
            if name == "self":
                continue

            annotation = param.annotation

            if name == "query":
                has_query = True
            elif name in self.SPECIAL_PARAMS:
                request_type = RequestType(name)
                has_files_in_form, has_files_in_body, body_file_field = (
                    self._analyze_special_param(name, annotation)
                )

        self._validate_request_constraints(request_type, has_files_in_form, sig)
        return (
            request_type,
            has_files_in_form,
            has_files_in_body,
            has_query,
            body_file_field,
        )

    def _analyze_special_param(
        self, param_name: str, annotation: Any
    ) -> Tuple[bool, bool, Optional[str]]:
        """Analiza parámetros especiales (body, form, form_data)"""
        has_files_in_form = has_files_in_body = False
        body_file_field: Optional[str] = None

        if param_name in {"form", "form_data"} and hasattr(annotation, "model_fields"):
            has_files_in_form = self.type_inspector.has_file_fields(annotation)
        elif param_name == "body":
            if hasattr(annotation, "model_fields"):
                has_files_in_body = self.type_inspector.has_file_fields(annotation)
                if has_files_in_body:
                    body_file_field = self._find_file_field(annotation)
            elif self.type_inspector.is_file_type(annotation):
                has_files_in_body = True

        return has_files_in_form, has_files_in_body, body_file_field

    def _find_file_field(self, annotation: Type[BaseModel]) -> Optional[str]:
        """Encuentra el primer campo de tipo File en un modelo"""
        for field_name, field_info in annotation.model_fields.items():
            if self.type_inspector.is_file_type(field_info.annotation):
                if field_info.annotation is File:
                    return field_name
        return None

    def _validate_request_constraints(
        self,
        request_type: Optional[RequestType],
        has_files_in_form: bool,
        sig: inspect.Signature,
    ):
        """Valida las restricciones de los tipos de request"""
        # Form no puede tener archivos
        if request_type == RequestType.FORM and has_files_in_form:
            raise ValueError(
                "Form no admite campos de tipo File. Use form_data en su lugar."
            )

        # Body no puede ser List[File]
        for name, param in sig.parameters.items():
            if name == "body":
                ann = param.annotation
                if (
                    get_origin(ann) is list
                    and get_args(ann)
                    and get_args(ann)[0] is File
                ):
                    raise ValueError(
                        "List[File] no está permitido en body. Use form_data."
                    )


class RequestCompiler:
    """Responsable de compilar la información del request"""

    def __init__(
        self, type_inspector: TypeInspector, request_detector: RequestTypeDetector
    ):
        self.type_inspector = type_inspector
        self.request_detector = request_detector

    def compile_request(self, func: Callable, path: str) -> CompiledRequest:
        """Compila la información del request una sola vez"""
        sig = inspect.signature(func)
        path_params = self._extract_path_params(path)

        (
            request_type,
            has_files_in_form,
            has_files_in_body,
            has_query,
            body_file_field,
        ) = self.request_detector.detect_request_info(sig)

        param_model = self._create_param_model(func, sig)
        actual_return_type, is_return_list, is_return_file = (
            self.type_inspector.detect_return_type(sig.return_annotation)
        )

        self._validate_return_type(is_return_list, actual_return_type)

        return CompiledRequest(
            param_model=param_model,
            path_params=path_params,
            request_type=request_type,
            has_query=has_query,
            return_type=actual_return_type,
            is_return_list=is_return_list,
            is_return_file=is_return_file,
            has_files_in_form=has_files_in_form,
            has_files_in_body=has_files_in_body,
            body_file_field=body_file_field,
        )

    def _extract_path_params(self, path: str) -> List[str]:
        """Extrae los parámetros de la ruta"""
        return re.findall(r"\{([^}]+)\}", path)

    def _create_param_model(
        self, func: Callable, sig: inspect.Signature
    ) -> Type[BaseModel]:
        """Crea el modelo Pydantic para validación de parámetros"""
        fields: Dict[str, Tuple[Any, Any]] = {}

        for name, param in sig.parameters.items():
            if name == "self":
                continue
            annotation = param.annotation
            default = param.default if param.default is not inspect._empty else ...
            fields[name] = (annotation, default)

        return create_model(f"{func.__name__}Params", **fields)

    def _validate_return_type(self, is_return_list: bool, actual_return_type: Type):
        """Valida el tipo de retorno"""
        if is_return_list and actual_return_type is File:
            raise ValueError(
                "List[File] como tipo de retorno no está soportado por el wrapper."
            )


class RequestBuilder:
    """Responsable de construir las requests HTTP"""

    def __init__(self, type_inspector: TypeInspector):
        self.type_inspector = type_inspector

    def build_request(
        self,
        base_url: str,
        path: str,
        compiled_req: CompiledRequest,
        validated: BaseModel,
        auth: Optional[httpx.Auth],
        instance_headers: Dict[str, str],
        allow_anonymous: bool = False,
        decorator_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Construye el diccionario de request para httpx"""

        url = self._build_url(base_url, path, compiled_req, validated)
        headers = self._combine_headers(instance_headers, decorator_headers)

        # Query siempre se procesa si existe
        query = self._build_query(validated, compiled_req.has_query)

        # Procesar body/form/form_data según el tipo
        json_body = form_data = files = content = None

        if compiled_req.request_type == RequestType.BODY:
            json_body, content, headers = self._build_body_request(
                validated, compiled_req, headers
            )
        elif compiled_req.request_type == RequestType.FORM:
            form_data = self._build_form_request(validated)
        elif compiled_req.request_type == RequestType.FORM_DATA:
            form_data, files = self._build_form_data_request(validated)

        return {
            "url": url,
            "auth": None if allow_anonymous else auth,
            "headers": headers,
            "params": query,
            "json": json_body,
            "data": form_data,
            "files": files,
            "content": content,
        }

    def _build_url(
        self,
        base_url: str,
        path: str,
        compiled_req: CompiledRequest,
        validated: BaseModel,
    ) -> str:
        """Construye la URL con parámetros de path"""
        url_params = {
            p: getattr(validated, p)
            for p in compiled_req.path_params
            if hasattr(validated, p)
        }
        return f"{base_url}{path.format(**url_params)}"

    def _combine_headers(
        self,
        instance_headers: Dict[str, str],
        decorator_headers: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Combina headers de instancia y decorator"""
        return {**instance_headers, **(decorator_headers or {})}

    def _build_query(
        self, validated: BaseModel, has_query: bool
    ) -> Optional[Dict[str, Any]]:
        """Construye parámetros de query si existen"""
        if not has_query:
            return None

        query_obj = getattr(validated, "query", None)
        if query_obj is None:
            return None

        return query_obj.model_dump() if isinstance(query_obj, BaseModel) else query_obj

    def _build_body_request(
        self,
        validated: BaseModel,
        compiled_req: CompiledRequest,
        headers: Dict[str, str],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[bytes], Dict[str, str]]:
        """Construye request de tipo body"""
        body_obj = getattr(validated, "body", None)
        if body_obj is None:
            return None, None, headers

        # Caso: body == File directamente
        if isinstance(body_obj, File):
            content = body_obj.content
            if not headers.get("Content-Type") and body_obj.content_type:
                headers["Content-Type"] = body_obj.content_type
            return None, content, headers

        # Caso: modelo con campo File
        if compiled_req.has_files_in_body and compiled_req.body_file_field:
            file_data = getattr(body_obj, compiled_req.body_file_field)

            if isinstance(file_data, list):
                raise ValueError("List[File] no está permitido en body. Use form_data.")

            content = file_data.content
            if not headers.get("Content-Type") and file_data.content_type:
                headers["Content-Type"] = file_data.content_type
            return None, content, headers

        # Caso JSON estándar
        return body_obj.model_dump(), None, headers

    def _build_form_request(self, validated: BaseModel) -> Optional[Dict[str, Any]]:
        """Construye request de tipo form (application/x-www-form-urlencoded)"""
        form_obj = getattr(validated, "form", None)
        if form_obj is None:
            return None
        return form_obj.model_dump()

    def _build_form_data_request(self, validated: BaseModel) -> Tuple[
        Optional[Dict[str, Any]],
        Optional[List[Tuple[str, Tuple[str | None, bytes | str, str | None]]]],
    ]:
        """Construye request de tipo form_data (multipart/form-data)"""
        form_data_obj = getattr(validated, "form_data", None)
        if form_data_obj is None:
            return None, None

        data, files = self._prepare_files_data(form_data_obj)

        # Forzar multipart/form-data aunque no haya files
        if not files:
            text_parts: List[Tuple[str, Tuple[None, str, None]]] = []
            for k, v in (data or {}).items():
                text_parts.append((k, (None, str(v), None)))
            return None, text_parts

        return data, files

    def _prepare_files_data(self, form_data_obj: BaseModel) -> Tuple[
        Optional[Dict[str, Any]],
        Optional[List[Tuple[str, Tuple[str | None, bytes | str, str | None]]]],
    ]:
        """Prepara datos y archivos para multipart/form-data"""
        data: Dict[str, Any] = {}
        files: List[Tuple[str, Tuple[str | None, bytes | str, str | None]]] = []

        for field_name, field_info in form_data_obj.model_fields.items():
            value = getattr(form_data_obj, field_name)
            if value is None:
                continue

            if self.type_inspector.is_file_type(field_info.annotation):
                if isinstance(value, list):
                    for f in value:
                        files.append(
                            (
                                field_name,
                                (
                                    f.filename or field_name,
                                    f.content,
                                    f.content_type or "application/octet-stream",
                                ),
                            )
                        )
                else:
                    files.append(
                        (
                            field_name,
                            (
                                value.filename or field_name,
                                value.content,
                                value.content_type or "application/octet-stream",
                            ),
                        )
                    )
            else:
                data[field_name] = value

        return (data or None), (files or None)


class ResponseParser:
    """Responsable de parsear las respuestas HTTP"""

    def parse_response(self, response: httpx.Response, compiled_req: CompiledRequest):
        """Parsea la respuesta según las especificaciones"""
        if response.status_code == 204:
            return ""

        content_type = response.headers.get("content-type", "").lower()

        # Caso File (único)
        if compiled_req.is_return_file:
            return self._parse_file_response(response, content_type)

        # Caso JSON o fallback texto
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

    def _parse_file_response(self, response: httpx.Response, content_type: str) -> File:
        """Parsea respuesta de tipo File"""
        filename = "download"
        if "filename=" in (cd := response.headers.get("content-disposition", "")):
            filename = cd.split("filename=")[1].strip('"')

        return File.model_validate(
            {
                "content": response.content,
                "filename": filename,
                "content_type": content_type or "application/octet-stream",
            }
        )

    def _parse_model(self, typ: Type, data: Any):
        """Parsea datos a modelo Pydantic si corresponde"""
        return (
            typ.model_validate(data)
            if inspect.isclass(typ) and issubclass(typ, BaseModel)
            else data
        )


class ArgumentValidator:
    """Responsable de validar argumentos contra modelos Pydantic"""

    def validate_args(self, compiled_req: CompiledRequest, args, kwargs) -> BaseModel:
        """Valida los argumentos contra el modelo Pydantic"""
        bound_args: Dict[str, Any] = {}

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


class HttpClient:
    """Cliente HTTP principal que orquesta todas las operaciones"""

    def __init__(
        self,
        base_url: str,
        auth: Optional[httpx.Auth] = ContextAuth(),
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.headers = headers or {}
        self._compiled_cache: Dict[str, CompiledRequest] = {}
        self.retryable_exceptions: Set[type] = {
            httpx.TimeoutException,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.NetworkError,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.ProtocolError,
            httpx.RemoteProtocolError,
            httpx.LocalProtocolError,
        }

        self.retryable_status_codes: Set[int] = {
            408,
            429,
            502,
            503,
            504,
            520,
            521,
            522,
            523,
            524,
        }
        # Inicializar componentes
        self.type_inspector = TypeInspector()
        self.request_detector = RequestTypeDetector(self.type_inspector)
        self.compiler = RequestCompiler(self.type_inspector, self.request_detector)
        self.request_builder = RequestBuilder(self.type_inspector)
        self.response_parser = ResponseParser()
        self.argument_validator = ArgumentValidator()

    def _is_retryable_exception(self, exception: Exception) -> bool:
        return type(exception) in self.retryable_exceptions

    def _is_retryable_http_status_error(self, exception: httpx.HTTPStatusError) -> bool:
        return exception.response.status_code in self.retryable_status_codes

    async def _calculate_backoff(self, attempt: int) -> None:
        if attempt > 0:
            wait_time = self.backoff_factor * (2 ** (attempt - 1))
            await asyncio.sleep(wait_time)

    async def _send_request(
        self, method: str, request: Dict[str, Any]
    ) -> httpx.Response:
        url = request.pop("url")
        cause = None
        status_code: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.request(method, url, **request)
                    status_code = response.status_code
                    response.raise_for_status()
                    return response

            except Exception as e:
                cause = e
                should_retry = False

                if isinstance(e, httpx.HTTPStatusError):
                    should_retry = self._is_retryable_http_status_error(e)
                else:
                    should_retry = self._is_retryable_exception(e)

                if should_retry and attempt < self.max_retries:
                    await self._calculate_backoff(attempt + 1)
                    continue
                else:
                    if not should_retry:
                        raise e
                    break

        raise HTTPRetryError(
            f"Request failed after {self.max_retries + 1} attempts. "
            f"Last error: {type(cause).__name__}: {str(cause)}",
            cause,
            self.max_retries + 1,
            url,
            status_code,
        )

    def _decorator(
        self,
        method: str,
        path: str,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ) -> Callable:
        """Decorator principal para métodos HTTP"""

        def wrapper(func: Callable) -> Callable:
            cache_key = f"{func.__module__}.{func.__qualname__}"
            compiled_req = self._compiled_cache.get(
                cache_key
            ) or self.compiler.compile_request(func, path)
            self._compiled_cache[cache_key] = compiled_req

            @functools.wraps(func)
            async def inner(*args, **kwargs) -> Any:
                validated = self.argument_validator.validate_args(
                    compiled_req, args, kwargs
                )

                request = self.request_builder.build_request(
                    self.base_url,
                    path,
                    compiled_req,
                    validated,
                    self.auth,
                    self.headers,
                    allow_anonymous,
                    headers,
                )

                response = await self._send_request(method, request)
                return self.response_parser.parse_response(response, compiled_req)

            return inner

        return wrapper

    # Decoradores HTTP
    def get(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._decorator("GET", path, allow_anonymous, headers)

    def post(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._decorator("POST", path, allow_anonymous, headers)

    def put(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._decorator("PUT", path, allow_anonymous, headers)

    def delete(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._decorator("DELETE", path, allow_anonymous, headers)

    def patch(
        self,
        path: str,
        *,
        allow_anonymous: bool = False,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._decorator("PATCH", path, allow_anonymous, headers)
