# app.py - Ejemplo de integración en tu aplicación
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor, ResponseInfo
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from common.telemetry import FilteringSpanProcessor

from console_exporter import TreeConsoleSpanExporter  # Tu exportador personalizado

class MiCalculadora:
    def __init__(self):
        self.tracer = trace.get_tracer(__name__)
    
    def procesar(self, operaciones):
        with self.tracer.start_as_current_span("procesar") as span:
            span.set_attribute("method_name", "procesar")
            span.set_attribute("operaciones.count", len(operaciones))
            
            resultados = []
            for op in operaciones:
                resultado = self.calcular(op['tipo'], op['a'], op['b'])
                resultados.append(resultado)
            
            return resultados
    
    def calcular(self, operacion, a, b):
        with self.tracer.start_as_current_span("calcular") as span:
            span.set_attribute("calculator.operation", operacion)
            span.set_attribute("calculator.operands", f"{a},{b}")
            
            if operacion == "suma":
                resultado = a + b
            elif operacion == "resta":
                resultado = a - b
            elif operacion == "multiplicacion":
                resultado = a * b
            elif operacion == "division":
                if b == 0:
                    span.set_status(trace.Status(trace.StatusCode.ERROR, "Division by zero"))
                    raise ValueError("No se puede dividir por cero")
                resultado = a / b
            else:
                span.set_status(trace.Status(trace.StatusCode.ERROR, f"Operación desconocida: {operacion}"))
                raise ValueError(f"Operación no soportada: {operacion}")
            
            span.set_attribute("calculator.result", str(resultado))
            return resultado

async def async_response_hook(span: trace.Span, request, response: ResponseInfo):
    if span.is_recording() and response.status_code <400:        
        span.set_status(trace.StatusCode.OK)

def setup_tracing():
    """Configura el sistema de trazado"""
    # Configurar el proveedor de trazas
    trace.set_tracer_provider(TracerProvider())
    
    # Configurar diferentes exportadores según el entorno
    import os
    env = os.getenv('ENV', 'development')
    
    if env == 'development':
        # En desarrollo: formato bonito en consola
        console_exporter = TreeConsoleSpanExporter(
            show_attributes=True,
            show_slow_only=False,
            min_duration_ms=0
        )
        span_processor = BatchSpanProcessor(console_exporter)
    
    elif env == 'production':
        # En producción: solo errores y operaciones lentas
        console_exporter = TreeConsoleSpanExporter(
            show_attributes=False,
            show_slow_only=True,
            min_duration_ms=100  # Solo mostrar operaciones > 100ms
        )
        span_processor = BatchSpanProcessor(console_exporter)
    
    else:
        # Testing: exportador nulo
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        span_processor = BatchSpanProcessor(ConsoleSpanExporter())
    
    trace.get_tracer_provider().add_span_processor(FilteringSpanProcessor(span_processor))
    
    # Instrumentar bibliotecas automáticamente
    HTTPXClientInstrumentor().instrument(async_response_hook = async_response_hook)
    # FastAPIInstrumentor().instrument_app(app)  # Se hace después de crear la app

# FastAPI app example
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import httpx
import uvicorn

app = FastAPI(title="Calculator API", version="1.0.0")


@app.middleware("http")
async def opentelemetry_status_middleware(request, call_next):
    response = await call_next(request)

    # Obtener el span actual (que será el root)
    span = trace.get_current_span()
    if span and span.is_recording() and response.status_code < 400:
        span.set_status(trace.StatusCode.OK)

    return response

# Configurar tracing antes de crear la app
setup_tracing()

# Instrumentar FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
FastAPIInstrumentor.instrument_app(app)

calculator = MiCalculadora()

# Modelos Pydantic
class Operacion(BaseModel):
    tipo: str
    a: float
    b: float

class CalculationRequest(BaseModel):
    operaciones: List[Operacion]

class CalculationResponse(BaseModel):
    resultados: List[float]
    external_data: Optional[dict] = None

@app.post("/test", response_model=CalculationResponse)
async def test_endpoint(request_data: CalculationRequest):
    with trace.get_tracer(__name__).start_as_current_span("POST /test") as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", "/test")
        span.set_attribute("request.operaciones_count", len(request_data.operaciones))
        
        try:
            # Convertir operaciones de Pydantic a dict
            operaciones = [
                {'tipo': op.tipo, 'a': op.a, 'b': op.b} 
                for op in request_data.operaciones
            ]
            
            # Procesar cálculos
            resultados = calculator.procesar(operaciones)
            
            # Hacer llamada externa con httpx
            async with httpx.AsyncClient() as client:
                external_response = await client.get('https://my-json-server.typicode.com/typicode/demo/posts/1')
                external_data = external_response.json() if external_response.status_code == 200 else None
            
            span.set_attribute("http.status_code", 200)
            span.set_attribute("response.resultados_count", len(resultados))
            
            return CalculationResponse(
                resultados=resultados,
                external_data=external_data
            )
            
        except Exception as e:
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            span.set_attribute("http.status_code", 500)
            span.set_attribute("error.message", str(e))
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "Calculator API with OpenTelemetry tracing"}

@app.get("/health")
async def health_check():
    with trace.get_tracer(__name__).start_as_current_span("GET /health") as span:
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.route", "/health")
        span.set_attribute("http.status_code", 200)
        return {"status": "healthy"}

if __name__ == '__main__':
    print("🚀 Iniciando FastAPI con trazado personalizado...")
    print("📊 Formato de consola habilitado")
    print("🔗 API Docs: http://localhost:8080/docs")
    print("🔗 Test endpoint: http://localhost:8080/test")
    
    uvicorn.run(app, host="127.0.0.1", port=8080,log_config=None,access_log=False)

# Configuración adicional para diferentes casos de uso
class TracingConfig:
    @staticmethod
    def development():
        return {
            'show_attributes': True,
            'show_slow_only': False,
            'min_duration_ms': 0
        }
    
    @staticmethod
    def production():
        return {
            'show_attributes': False,
            'show_slow_only': True,
            'min_duration_ms': 100
        }
    
    @staticmethod
    def debugging():
        return {
            'show_attributes': True,
            'show_slow_only': False,
            'min_duration_ms': 0,
            # Configuraciones adicionales para debugging profundo
        }

# Script para probar el formato
def test_console_output():
    """Script para probar la salida del console exporter"""
    tracer = trace.get_tracer(__name__)
    
    # Simular trace complejo
    with tracer.start_as_current_span("POST /api/calculate") as root:
        root.set_attribute("http.method", "POST")
        root.set_attribute("http.status_code", 200)
        root.set_attribute("user.id", "user123")
        
        with tracer.start_as_current_span("validate_input") as validation:
            validation.set_attribute("validation.rules_applied", 3)
            import time; time.sleep(0.001)
        
        with tracer.start_as_current_span("business_logic") as business:
            with tracer.start_as_current_span("calcular") as calc1:
                calc1.set_attribute("calculator.operation", "suma")
                calc1.set_attribute("calculator.operands", "10,5")
                calc1.set_attribute("calculator.result", "15")
                time.sleep(0.002)
            
            with tracer.start_as_current_span("save_to_db") as db:
                db.set_attribute("db.statement", "INSERT INTO calculations VALUES (?)")
                db.set_attribute("db.name", "calculator_db")
                time.sleep(0.005)
        
        with tracer.start_as_current_span("GET external_api") as ext:
            ext.set_attribute("http.method", "GET")
            ext.set_attribute("http.url", "https://api.example.com/data")
            ext.set_attribute("http.status_code", 200)
            time.sleep(0.1)  # Simular llamada lenta

if __name__ == "__main__":
    print("🧪 Ejecutando prueba de formato...")
    setup_tracing()
    test_console_output()