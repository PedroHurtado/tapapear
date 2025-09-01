import httpx
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from common.telemetry import traced_class, get_logger, get_tracer, setup_telemetry


@traced_class(["procesar", "calcular"])
class MiCalculadora:
    def procesar(self, x, y):
        return self.calcular(x) + self.calcular(y)

    def calcular(self, x):
        return x * 2

    def metodo_no_trazado(self):
        return "No aparece en traces"


calculadora = MiCalculadora()

app = FastAPI(title="Telemetry Test API")

# IMPORTANTE: Limpiar handlers de exception antes de configurar telemetría
app.exception_handlers.clear()

# Initialize telemetry BEFORE creating FastAPI app
setup_telemetry(service_name="test-service", service_version="1.0.0", fastapi_app=app)

# Get logger and tracer
logger = get_logger(__name__)
tracer = get_tracer(__name__)


class TestRequest(BaseModel):
    name: str
    message: str


class TestResponse(BaseModel):
    id: int
    name: str
    message: str
    status: str


# Exception handler que NO propaga a consola
@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # Log controlado vía structlog (aparecerá en traza)
    logger.error(
        "Unhandled exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=str(request.url),
    )

    # Marcar el span actual como error
    span = trace.get_current_span()
    if span and span.is_recording():
        span.set_status(Status(StatusCode.ERROR, str(exc)))
        span.set_attribute("error.type", type(exc).__name__)
        span.set_attribute("error.message", str(exc))

    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# Middleware para establecer status del span según response code
@app.middleware("http")
async def opentelemetry_status_middleware(request: Request, call_next):
    response = await call_next(request)

    # Obtener el span actual (que será el root)
    span = trace.get_current_span()
    if span and span.is_recording():
        if 400 <= response.status_code < 500:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        else:
            span.set_status(Status(StatusCode.OK))

        # También puedes agregar atributos
        span.set_attribute("http.response.status_code", response.status_code)

    return response


@app.get("/")
async def root():
    logger.info("Root endpoint called")

    calculadora.procesar(10, 20)

    await simulate_external_call()

    return {"message": "Hello OpenTelemetry!"}


@app.get("/health")
async def health():
    logger.info("Health check requested")
    return {"status": "healthy", "service": "test-service"}


@app.post("/test")
async def test_endpoint(request: TestRequest) -> TestResponse:

    calculadora.procesar(1, 2)

    await simulate_external_call()

    return TestResponse(
        id=123,
        name=request.name,
        message=f"Processed: {request.message}",
        status="completed",
    )


async def simulate_external_call():
    """
    Función que simula llamada externa y maneja errores correctamente
    para que aparezcan en la traza de HTTPX sin llegar a consola
    """
    current_span = trace.get_current_span()

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://my-json-server.typicode.com/typicode/demo/posts/125"
            )
            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        # Error HTTP - se captura en el span de HTTPX automáticamente
        logger.error(
            "HTTP error in external call",
            status_code=e.response.status_code,
            url=str(e.request.url),
        )

        if current_span and current_span.is_recording():
            current_span.add_event(
                "external_call_failed",
                {
                    "error.type": "HTTPStatusError",
                    "http.status_code": e.response.status_code,
                    "http.url": str(e.request.url),
                },
            )

        # Lanzar excepción genérica que será capturada por el exception handler
        raise Exception(f"External API returned {e.response.status_code}")

    except httpx.RequestError as e:
        # Error de conexión/red
        logger.error(
            "Request error in external call",
            error=str(e),
            url=str(e.request.url) if hasattr(e, "request") else "unknown",
        )

        if current_span and current_span.is_recording():
            current_span.add_event(
                "external_call_failed",
                {"error.type": "RequestError", "error.message": str(e)},
            )

        # Lanzar excepción genérica
        raise Exception("External service unavailable")

    except Exception as e:
        # Cualquier otro error
        logger.error("Unexpected error in external call", error=str(e))

        if current_span and current_span.is_recording():
            current_span.add_event(
                "external_call_failed",
                {"error.type": type(e).__name__, "error.message": str(e)},
            )

        # Re-lanzar la excepción original o una nueva
        raise Exception("External call failed")


@app.get("/error")
async def test_error():
    """Test error handling and logging"""
    logger.info("Error endpoint called")

    with tracer.start_as_current_span("error_operation"):
        logger.error("Simulated error occurred", error_type="test_error")
        raise Exception("This is a test error")


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting test application")
    # Disable uvicorn's default logging to see our structured logs
    uvicorn.run(app, port=8080, log_config=None, access_log=False)
