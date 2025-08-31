import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from common.telemetry.config import setup_telemetry, get_logger, get_tracer
from common.telemetry.decorators import traced_class

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
app.exception_handlers.clear()

# Initialize telemetry BEFORE creating FastAPI app
setup_telemetry(
    service_name="test-service",
    service_version="1.0.0",    
    fastapi_app=app
)

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


@app.get("/")
async def root():
    logger.info("Root endpoint called")

    calculadora.procesar(10,20)

    await simulate_external_call()
    
    return {"message": "Hello OpenTelemetry!"}


@app.get("/health")
async def health():
    logger.info("Health check requested")
    return {"status": "healthy", "service": "test-service"}


@app.post("/test")
async def test_endpoint(request: TestRequest) -> TestResponse:   
    
    

    # Simulate calling another service

    await simulate_external_call()
    
    return TestResponse(
        id=123,
        name=request.name,
        message=f"Processed: {request.message}",
        status="completed"
    )        
        
        
    


async def simulate_external_call():       
   
        try:
            async with httpx.AsyncClient() as client:                
                response = await client.get("https://my-json-server.typicode.com/typicode/demo/posts")                
                response.raise_for_status()
        except Exception as e:
             raise e


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
    uvicorn.run(app,  port=8080, log_config=None, access_log=False)