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

# OpenTelemetry imports
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.semconv.trace import SpanAttributes


class HTTPRetryError(Exception):
    def __init__(
        self,
        message: str,        
        attempts: int,
        url: str,
        status_code: Optional[int]=None,
        cause: Optional[Exception]=None,
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


class TelemetryManager:
    """Manager centralizado para telemetría OpenTelemetry"""

    def __init__(self, tracer: trace.Tracer):
        self.tracer = tracer

    def create_main_span(self, method: str, path_template: str):
        """Crea el span principal del request"""
        return self.tracer.start_as_current_span(
            name=f"infrastructure.{method} {path_template}",
            record_exception=False,            
        )

    def create_child_span(self, name: str, parent_span=None):
        """Crea un span hijo (usando el span padre si se pasa, o el actual en contexto)"""
        trace_name = f"infrastructure.{name}"
        if parent_span:
            ctx = trace.set_span_in_context(parent_span)
            return self.tracer.start_as_current_span(
                name=trace_name,
                context=ctx,
                record_exception=False
                
            )
        return self.tracer.start_as_current_span(
            name=trace_name            
        )

    def set_main_span_attributes(
        self,
        span,
        method: str,
        url: str,
        path_template: str,
        compiled_req: CompiledRequest,
        func_name: str,
        class_name: str,
        allow_anonymous: bool,
        auth_type: str,
        has_token: bool,
        cache_hit: bool,
    ):
        """Establece atributos del span principal"""
        span.set_attribute("http.request.method", method)
        span.set_attribute("url.full", url)
        span.set_attribute("url.template", path_template)
        span.set_attribute("httpclient.method_name", func_name)
        span.set_attribute("httpclient.class_name", class_name)
        span.set_attribute("httpclient.allow_anonymous", allow_anonymous)
        span.set_attribute("httpclient.auth.type", auth_type)
        span.set_attribute("httpclient.auth.has_token", has_token)
        span.set_attribute("httpclient.compilation.cache_hit", cache_hit)

        if compiled_req.request_type:
            span.set_attribute(
                "httpclient.request_type", compiled_req.request_type.value
            )

        span.set_attribute(
            "httpclient.has_files",
            compiled_req.has_files_in_form or compiled_req.has_files_in_body,
        )
        span.set_attribute("httpclient.has_query", compiled_req.has_query)
        span.set_attribute(
            "httpclient.return_type",
            compiled_req.return_type.__name__
            if compiled_req.return_type != inspect.Signature.empty
            else "Any",
        )
        span.set_attribute("httpclient.is_return_list", compiled_req.is_return_list)
        span.set_attribute("httpclient.is_return_file", compiled_req.is_return_file)

    def set_response_attributes(self, span, response: httpx.Response):
        """Establece atributos de respuesta"""
        span.set_attribute("http.response.status_code", response.status_code)
        span.set_attribute("http.response.body.size", len(response.content))

        content_type = response.headers.get("content-type")
        if content_type:
            span.set_attribute("httpclient.response.content_type", content_type)

    def set_request_size_attributes(self, span, request_data: Dict[str, Any]):
        """Establece atributos de tamaño del request"""
        size = 0
        if request_data.get("json"):
            size += len(str(request_data["json"]).encode())
        elif request_data.get("content"):
            size += len(request_data["content"])
        elif request_data.get("data"):
            size += len(str(request_data["data"]).encode())

        if size > 0:
            span.set_attribute("http.request.body.size", size)

    def set_files_attributes(self, span, files_data):
        """Establece atributos de archivos"""
        if not files_data:
            return

        file_count = len(files_data) if isinstance(files_data, list) else 1
        total_size = 0

        if isinstance(files_data, list):
            for _, (_, content, _) in files_data:
                if isinstance(content, bytes):
                    total_size += len(content)

        span.set_attribute("httpclient.files.count", file_count)
        if total_size > 0:
            span.set_attribute("httpclient.files.total_size", total_size)

    def set_validation_attributes(self, span, param_model: Type[BaseModel]):
        """Establece atributos de validación"""
        span.set_attribute(
            "httpclient.validation.param_count", len(param_model.model_fields)
        )
        span.set_attribute("httpclient.validation.model_name", param_model.__name__)

    def set_build_attributes(
        self,
        span,
        path_params: List[str],
        has_query: bool,
        request_type: Optional[RequestType],
        query_data,
    ):
        """Establece atributos de construcción del request"""
        span.set_attribute("httpclient.build.url_params_count", len(path_params))
        span.set_attribute("httpclient.build.has_body", request_type == RequestType.BODY)
        span.set_attribute(
            "httpclient.build.has_form_data", request_type == RequestType.FORM_DATA
        )

        if has_query and query_data:
            span.set_attribute("httpclient.build.query_params_count", len(query_data))

    def set_retry_attributes(
        self,
        span,
        attempt: int,
        max_attempts: int,
        backoff_factor: float,
        wait_time: float,
        reason: str,
        last_status_code: Optional[int],
        exception_type: Optional[str],
    ):
        """Establece atributos de retry"""
        span.set_attribute("httpclient.retry.attempt", attempt)
        span.set_attribute("httpclient.retry.max_attempts", max_attempts)
        span.set_attribute("httpclient.retry.backoff_factor", backoff_factor)
        span.set_attribute("httpclient.retry.wait_time_ms", int(wait_time * 1000))
        span.set_attribute("httpclient.retry.reason", reason)

        if last_status_code:
            span.set_attribute("httpclient.retry.last_status_code", last_status_code)
        if exception_type:
            span.set_attribute("httpclient.retry.exception_type", exception_type)

    def set_parse_attributes(
        self,
        span,
        content_type: Optional[str],
        return_type: Type,
        is_file: bool,
        is_list: bool,
        item_count: Optional[int],
    ):
        """Establece atributos de parsing"""
        if content_type:
            span.set_attribute("httpclient.parse.content_type", content_type)

        span.set_attribute(
            "httpclient.parse.response_type",
            return_type.__name__
            if return_type != inspect.Signature.empty
            else "Any",
        )
        span.set_attribute("httpclient.parse.is_file", is_file)
        span.set_attribute("httpclient.parse.is_list", is_list)

        if is_list and item_count is not None:
            span.set_attribute("httpclient.parse.item_count", item_count)

    def finish_span_ok(self, span):
        """Finaliza un span con status OK"""
        if span and span.is_recording():
            span.set_status(Status(StatusCode.OK))

    def finish_span_error(self, span, error: Exception, record_exception: bool = True):
        """Finaliza un span con status ERROR.
        
        Args:
            span: El span a finalizar
            error: La excepción que causó el error
            record_exception: Si es True, registra los detalles completos de la excepción.
                            Si es False, solo marca el status como ERROR sin detalles.
        """
        """
        if span and span.is_recording():
            if record_exception:
                # Span donde se origina la excepción: registrar detalles completos
                span.set_status(Status(StatusCode.ERROR, str(error)))
                #span.record_exception(error)
            else:
                # Spans padre: solo marcar como ERROR sin detalles de la excepción
                span.set_status(Status(StatusCode.ERROR))
        """


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

    def __init__(self, telemetry: TelemetryManager):
        self.telemetry = telemetry

    def parse_response(self, response: httpx.Response, compiled_req: CompiledRequest, parent_span):
        """Parsea la respuesta según las especificaciones"""
        with self.telemetry.create_child_span("parse_response", parent_span) as parse_span:
            try:
                content_type = response.headers.get("content-type", "").lower()
                result = None
                item_count = None

                if response.status_code == 204:
                    result = ""
                elif compiled_req.is_return_file:
                    result = self._parse_file_response(response, content_type)
                else:
                    # Caso JSON o fallback texto
                    try:
                        data = response.json()
                    except ValueError:
                        data = response.text

                    if compiled_req.return_type == inspect.Signature.empty:
                        result = data
                    elif compiled_req.is_return_list:
                        if data is None:
                            result = []
                            item_count = 0
                        else:
                            result = [
                                self._parse_model(compiled_req.return_type, item) for item in data
                            ]
                            item_count = len(result)
                    else:
                        result = self._parse_model(compiled_req.return_type, data)

                # Establecer atributos de telemetría
                self.telemetry.set_parse_attributes(
                    parse_span,
                    content_type,
                    compiled_req.return_type,
                    compiled_req.is_return_file,
                    compiled_req.is_return_list,
                    item_count
                )

                self.telemetry.finish_span_ok(parse_span)
                return result

            except Exception as e:
                self.telemetry.finish_span_error(parse_span, e, True)  # Registrar en el nivel donde se origina
                raise

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

    def __init__(self, telemetry: TelemetryManager):
        self.telemetry = telemetry

    def validate_args(self, compiled_req: CompiledRequest, args, kwargs, parent_span) -> BaseModel:
        """Valida los argumentos contra el modelo Pydantic"""
        with self.telemetry.create_child_span("validate_arguments", parent_span) as validation_span:
            try:
                bound_args: Dict[str, Any] = {}

                # Obtener los nombres de parámetros del modelo en orden
                param_names = list(compiled_req.param_model.model_fields.keys())

                if args:                   
                    start_index = 0
                    # Mapear argumentos posicionales a nombres de parámetros
                    for i, arg in enumerate(args[start_index:]):
                        if i < len(param_names):
                            bound_args[param_names[i]] = arg

                # Combinar con argumentos nombrados (kwargs tienen precedencia)
                bound_args.update(kwargs)

                # Establecer atributos de telemetría
                self.telemetry.set_validation_attributes(validation_span, compiled_req.param_model)

                validated = compiled_req.param_model(**bound_args)
                self.telemetry.finish_span_ok(validation_span)
                return validated            
            except Exception as e:
                self.telemetry.finish_span_error(validation_span, e, True)
                raise


class HttpClient:
    """Cliente HTTP principal que orquesta todas las operaciones"""

    def __init__(
        self,
        base_url: str,
        auth: Optional[httpx.Auth] = ContextAuth(),
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
        tracer_name: str = "httpclient",
    ):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.headers = headers or {}
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._compiled_cache: Dict[str, CompiledRequest] = {}
        
        # Configurar telemetría
        self.tracer = trace.get_tracer(tracer_name)
        self.telemetry = TelemetryManager(self.tracer)
        
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
        self.response_parser = ResponseParser(self.telemetry)
        self.argument_validator = ArgumentValidator(self.telemetry)

    def _get_auth_info(self) -> Tuple[str, bool]:
        """Obtiene información de autenticación para telemetría"""
        if self.auth is None:
            return "none", False
        elif isinstance(self.auth, ContextAuth):
            token = jwt_token_var.get()
            return "context", token is not None
        else:
            return "custom", True

    def _is_retryable_exception(self, exception: Exception) -> bool:
        return type(exception) in self.retryable_exceptions

    def _is_retryable_http_status_error(self, exception: httpx.HTTPStatusError) -> bool:
        return exception.response.status_code in self.retryable_status_codes

    async def _calculate_backoff(self, attempt: int) -> float:
        wait_time = self.backoff_factor * (2 ** (attempt - 1))
        if attempt > 0:
            await asyncio.sleep(wait_time)
        return wait_time

    async def _send_request_with_retries(
        self, method: str, request: Dict[str, Any], parent_span
    ) -> httpx.Response:
        """Envía el request con lógica de retry y telemetría"""
        url = request["url"]
        cause = None
        status_code: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            retry_span = None
            
            # Crear span de retry solo si no es el primer intento
            if attempt > 0:
                retry_span = self.telemetry.create_child_span(f"retry_attempt_{attempt}", parent_span)

            try:
                # Crear span HTTP para cada intento
                with self.telemetry.create_child_span("http_request", parent_span) as http_span:
                    try:
                        async with httpx.AsyncClient() as client:
                            response = await client.request(method, url, **{k: v for k, v in request.items() if k != "url"})
                            status_code = response.status_code
                            
                            # Establecer atributos del span HTTP
                            http_span.set_attribute("http.request.method", method)
                            http_span.set_attribute("http.response.status_code", status_code)
                            http_span.set_attribute("network.protocol.name", "http")
                            
                            # Intentar obtener información adicional
                            if hasattr(response, 'url') and response.url:
                                http_span.set_attribute("server.address", response.url.host or "unknown")
                                if response.url.port:
                                    http_span.set_attribute("server.port", response.url.port)

                            response.raise_for_status()
                            self.telemetry.finish_span_ok(http_span)
                            
                            # Si llegamos aquí, el request fue exitoso
                            if retry_span:
                                self.telemetry.finish_span_ok(retry_span)
                            
                            return response

                    except Exception as e:
                        # El span HTTP falló
                        self.telemetry.finish_span_error(http_span, e, True)  # Registrar en el span HTTP
                        raise e

            except Exception as e:
                cause = e
                should_retry = False
                reason = "unknown"
                exception_type = type(e).__name__

                if isinstance(e, httpx.HTTPStatusError):
                    should_retry = self._is_retryable_http_status_error(e)
                    reason = "status_code"
                    status_code = e.response.status_code
                else:
                    should_retry = self._is_retryable_exception(e)
                    if should_retry:
                        if "timeout" in exception_type.lower():
                            reason = "timeout"
                        elif "network" in exception_type.lower() or "connect" in exception_type.lower():
                            reason = "network_error"

                if should_retry and attempt < self.max_retries:
                    wait_time = await self._calculate_backoff(attempt + 1)
                    
                    # Establecer atributos del span de retry
                    if retry_span:
                        self.telemetry.set_retry_attributes(
                            retry_span,
                            attempt + 1,
                            self.max_retries,
                            self.backoff_factor,
                            wait_time,
                            reason,
                            status_code,
                            exception_type
                        )
                        self.telemetry.finish_span_ok(retry_span)
                    
                    continue
                else:
                    # No se puede reintentar o se agotaron los reintentos
                    if retry_span:
                        self.telemetry.set_retry_attributes(
                            retry_span,
                            attempt + 1,
                            self.max_retries,
                            self.backoff_factor,
                            0.0,
                            reason,
                            status_code,
                            exception_type
                        )
                        self.telemetry.finish_span_error(retry_span, e, False)  # No registrar en el span de retry
                    
                    if not should_retry:
                        raise e
                    break

        # Si llegamos aquí, se agotaron todos los reintentos
        retry_error = HTTPRetryError(
            f"Request failed after {self.max_retries + 1} attempts. "
            f"Last error: {type(cause).__name__}: {str(cause)}",
            self.max_retries + 1,
            url,
            status_code,
            cause,
        )
        raise retry_error

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
            
            @functools.wraps(func)
            async def inner(*args, **kwargs) -> Any:
                # Crear span principal
                with self.telemetry.create_main_span(method, path) as main_span:
                    try:
                        # Compilar request (con cache)
                        cache_hit = cache_key in self._compiled_cache
                        if not cache_hit:
                            self._compiled_cache[cache_key] = self.compiler.compile_request(func, path)
                        compiled_req = self._compiled_cache[cache_key]

                        # Obtener información de autenticación
                        auth_type, has_token = self._get_auth_info()
                        
                        # Obtener información de clase y función
                        class_name = args[0].__class__.__name__ if args else "unknown"
                        func_name = func.__name__

                        try:
                            # Validar argumentos
                            validated = self.argument_validator.validate_args(
                                compiled_req, args, kwargs, main_span
                            )
                        except Exception as e:
                            # No registrar la excepción en el span principal
                            self.telemetry.finish_span_error(main_span, e, False)
                            raise

                        # Construir request
                        with self.telemetry.create_child_span("build_request", main_span) as build_span:
                            try:
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

                                # Establecer atributos de construcción
                                query_data = request.get("params")
                                self.telemetry.set_build_attributes(
                                    build_span,
                                    compiled_req.path_params,
                                    compiled_req.has_query,
                                    compiled_req.request_type,
                                    query_data
                                )

                                self.telemetry.finish_span_ok(build_span)

                            except Exception as e:
                                self.telemetry.finish_span_error(build_span, e, True)
                                raise

                        # Establecer atributos del span principal
                        self.telemetry.set_main_span_attributes(
                            main_span,
                            method,
                            request["url"],
                            path,
                            compiled_req,
                            func_name,
                            class_name,
                            allow_anonymous,
                            auth_type,
                            has_token,
                            cache_hit
                        )

                        # Establecer atributos de tamaño del request
                        self.telemetry.set_request_size_attributes(main_span, request)

                        # Establecer atributos de archivos si aplica
                        files_data = request.get("files")
                        if files_data:
                            self.telemetry.set_files_attributes(main_span, files_data)

                        # Enviar request
                        response = await self._send_request_with_retries(method, request, main_span)

                        # Establecer atributos de respuesta
                        self.telemetry.set_response_attributes(main_span, response)

                        # Parsear respuesta
                        result = self.response_parser.parse_response(response, compiled_req, main_span)

                        # Finalizar span principal con éxito
                        self.telemetry.finish_span_ok(main_span)
                        return result

                    except Exception as e:
                        # Finalizar span principal con error
                        self.telemetry.finish_span_error(main_span, e, False)
                        raise

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