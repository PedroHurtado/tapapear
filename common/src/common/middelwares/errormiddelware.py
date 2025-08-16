from typing import Optional,Dict
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import ValidationException
from starlette.types import ASGIApp, Receive, Scope, Send, Message
from common.errors import ErrorResponse
import json

class SendInterceptor:
    """
    Intercepta respuestas HTTP para reescribir cuerpos de error (>=400) con un JSON uniforme,
    sin violar el orden ASGI. Si es error, NO envía el 'start' original; bufferiza el body y
    después emite un único 'http.response.start' + 'http.response.body' con nuestro JSON.
    """
    def __init__(self, original_send: Send, request_path: str):
        self.original_send = original_send
        self.request_path = request_path
        self.status_code: Optional[int] = None
        self.headers: Dict[bytes, bytes] = {}
        self.body_parts: list[bytes] = []
        self._intercept_error = False  # True si debemos suprimir la respuesta original y enviar la nuestra

    async def send(self, message: Message) -> None:
        msg_type = message["type"]

        if msg_type == "http.response.start":
            # Guardamos status y headers
            self.status_code = message["status"]
            self.headers = dict(message.get("headers", []))

            if self.status_code and self.status_code >= 400:
                # Es error: NO reenviamos este start; esperaremos a tener todo el body
                self._intercept_error = True
                return
            else:
                # No es error: pasamos tal cual
                await self.original_send(message)
                return

        elif msg_type == "http.response.body":
            if self._intercept_error:
                # Bufferizar todo el cuerpo del error original
                body = message.get("body", b"")
                if body:
                    self.body_parts.append(body)

                if not message.get("more_body", False):
                    # Fin del body: construimos nuestra respuesta JSON
                    original_body = b"".join(self.body_parts)
                    error_response = await self._create_custom_error_response(original_body)

                    # Enviamos UN único start + body con nuestro JSON
                    await self.original_send({
                        "type": "http.response.start",
                        "status": self.status_code,
                        "headers": [(b"content-type", b"application/json")],
                    })
                    await self.original_send({
                        "type": "http.response.body",
                        "body": error_response.encode(),
                        "more_body": False,
                    })

                    # Reset por seguridad
                    self._intercept_error = False
                    self.body_parts.clear()
                return
            else:
                # No es error: passthrough
                await self.original_send(message)
                return

        # Cualquier otro tipo de mensaje ASGI (poco común en http) se pasa tal cual
        await self.original_send(message)

    async def _create_custom_error_response(self, original_body: bytes) -> str:
        """Crea una respuesta de error personalizada"""
        try:
            original_data = json.loads(original_body.decode()) if original_body else {}
        except Exception:
            original_data = {}

        detail = original_data.get("detail", "Error")

        exception_name = "HTTPException"
        if self.status_code == 403:
            exception_name = "ForbiddenException"
        elif self.status_code == 401:
            exception_name = "UnauthorizedException"
        elif self.status_code == 404:
            exception_name = "NotFoundException"        
        elif self.status_code == 422:
            exception_name = "ValidationException"

        response = ErrorResponse(
            
            status=self.status_code,
            error=self._get_error_name_from_status(self.status_code),
            exception=exception_name,
            message=detail if isinstance(detail, str) else str(detail),
            path=self.request_path
        )

        data = response.model_dump()        
        return json.dumps(data)

    def _get_error_name_from_status(self, status_code: int) -> str:
        status_map = {
            400: "Bad Request Error",
            401: "Unauthorized Error",
            403: "Forbidden Error",
            404: "Not Found Error",
            405: "Method Not Allowed",
            415: "Unsupported Media Type",
            422: "Validation Error",
            500: "Internal Server Error",
        }
        return status_map.get(status_code, f"HTTP {status_code} Error")


def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    """Maneja las excepciones HTTP y devuelve una respuesta personalizada"""
    response = ErrorResponse(
        
        status=exc.status_code,
        error=f"HTTP {exc.status_code} Error",
        exception="HTTPException",
        message=str(exc.detail),
        path=request.url.path,
    )
    data = response.model_dump()    
    return JSONResponse(status_code=exc.status_code, content=data)


class ErrorMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        responder = SendInterceptor(send, request.url.path)

        try:
            await self.app(scope, receive, responder.send)

        except HTTPException as exc:
            # Manejamos excepciones que no fueron procesadas por FastAPI
            json_response = handle_http_exception(request, exc)
            await json_response(scope, receive, send)
        except ValidationException as exc:
            # Manejamos excepciones que no fueron procesadas por FastAPI
            response = ErrorResponse(                
                status=422,
                error="Validation Error",
                exception=exc.__class__.__name__,
                message=exc.errors(),
                path=request.url.path,
            )

            data = response.model_dump()            
            json_response = JSONResponse(status_code=422, content=data)
            await json_response(scope, receive, send)

        except Exception as exc:
            # Manejamos excepciones no HTTP           
            response = ErrorResponse(                
                status=500,
                error="Internal Server Error",
                exception=exc.__class__.__name__,
                message=str(exc),
                path=request.url.path,
            )

            data = response.model_dump()          
            json_response = JSONResponse(status_code=500, content=data)
            await json_response(scope, receive, send)
