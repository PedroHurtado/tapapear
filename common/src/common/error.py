from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime
from starlette.types import ASGIApp, Receive, Scope, Send

class ErrorResponse(BaseModel):
    method: str
    path: str
    timestamp: datetime
    message: str

# Middleware de errores (ASGI puro)
class ErrorHandlerMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        responder = SendInterceptor(send)
        try:
            await self.app(scope, receive, responder.send)
            await responder.flush()
            print(responder.status_code)
        except HTTPException as exc:
            response = ErrorResponse(
                method=request.method,
                path=request.url.path,
                timestamp=datetime.now(),
                message=exc.detail,
            )
            await JSONResponse(status_code=exc.status_code, content=response.model_dump_json())(scope, receive, send)
        except Exception as exc:
            response = ErrorResponse(
                method=request.method,
                path=request.url.path,
                timestamp=datetime.now(),
                message="Internal Server Error",
            )
            await JSONResponse(status_code=500, content=response.model_dump_json())(scope, receive, send)

# Middleware para capturar body y status (ASGI puro)
class CaptureResponseMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        responder = SendInterceptor(send)
        await self.app(scope, receive, responder.send)
        await responder.flush()

        print("Status code:", responder.status_code)
        print("Body:", responder.body.decode())

# Helper para interceptar el send
class SendInterceptor:
    def __init__(self, send: Send):
        self._send = send  # guardamos la función original
        self.body = b""
        self.status_code = None
        self.headers = []

    async def send(self, message):
        if message["type"] == "http.response.start":
            self.status_code = message["status"]
            self.headers = message.get("headers", [])
        elif message["type"] == "http.response.body":
            self.body += message.get("body", b"")
        # Llamamos a la función original
        await self._send(message)

    async def flush(self):
        pass


# FastAPI app
app = FastAPI()

items = {1: "The Foo Wrestlers"}

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    if item_id not in items:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"item": items[item_id]}

# Añadimos middlewares
app.add_middleware(ErrorHandlerMiddleware)
#app.add_middleware(CaptureResponseMiddleware)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("error:app", host="0.0.0.0", port=8081, reload=True)

