from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import ValidationException
from starlette.exceptions import HTTPException
from common.errors import ErrorResponse
from ._exception import ApplicationException
from ._constants import UNPROCESSABLEENTITY, INTERNALSERVERERROR


def _create_error_response(
    status: int, 
    error: str, 
    exception_name: str, 
    message: str | list, 
    path: str
) -> JSONResponse:
    """Crea una respuesta de error estandarizada."""
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            status=status,
            error=error,
            exception=exception_name,
            message=message,
            path=path,
        ).model_dump(),
    )


def setup_exception_handlers(app: FastAPI) -> None:
    """
    Registra todos los exception handlers necesarios.
    """

    @app.exception_handler(ApplicationException)
    async def application_exception_handler(
        request: Request, exc: ApplicationException
    ) -> JSONResponse:
        exc.from_request(request)
        return _create_error_response(
            status=exc.status,
            error=exc.error,
            exception_name=exc.exception,
            message=exc.message,
            path=exc.path or str(request.url.path),
        )

    @app.exception_handler(ValidationException)
    async def validation_exception_handler(
        request: Request, exc: ValidationException
    ) -> JSONResponse:
        return _create_error_response(
            status=UNPROCESSABLEENTITY,
            error="Validation Error",
            exception_name=type(exc).__name__,
            message=exc.errors(),
            path=str(request.url.path),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        return _create_error_response(
            status=exc.status_code,
            error="HTTP Exception",
            exception_name=type(exc).__name__,
            message=exc.detail,
            path=str(request.url.path),
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Control especial para HTTPException en middlewares
        if isinstance(exc, HTTPException):
            return await http_exception_handler(request, exc)
        
        return _create_error_response(
            status=INTERNALSERVERERROR,
            error="Internal Server Error",
            exception_name=type(exc).__name__,
            message=str(exc),
            path=str(request.url.path),
        )