from fastapi import FastAPI, HTTPException, Security
from common.middelwares import AuthMiddleware, ErrorMiddleware
from common.security import(    
    authorize,allow_anonymous, 
    setup_security_dependencies,
    principal_ctx,
    security_scheme,
    Principal
)
from common.context import get_app_context
from common.ioc import AppContainer, inject,deps,component
from common.openapi import(
    setup_custom_openapi,
    build_error_responses,
    FeatureModel
)
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):    
    context = get_app_context()
    module_names = [__name__]  
    container = AppContainer()
    container.wire(module_names)    

    setup_security_dependencies(app)
    context.allow_anonymous_routes.update(context.docs_path)           
    yield

    
# create app
app = FastAPI(
    lifespan=lifespan,
    title="Mi API con Auth",
    description="Ejemplo con autenticación automática",
    version="1.0.0",
)

# ============================================================
# App y endpoints de ejemplo
# ============================================================

setup_custom_openapi(app)

# Agregar middlewares en el orden correcto
app.add_middleware(AuthMiddleware)
app.add_middleware(ErrorMiddleware)
app.exception_handlers.clear()


@component
class Service:    
    @inject
    def __call__(self, principal:Principal=deps(Principal)):
        print(principal)

class Request(FeatureModel):
    id: int


class Response(FeatureModel):
    id: int


@app.post("/public", 
          summary="El perro de San Roque no tiene Rabo",   
          responses=  build_error_responses(400,409)     
)
@allow_anonymous
async def public_endpoint(req: Request) -> Response:
    return Response(id=req.id)


@app.get("/private")
async def private_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Hola {principal.username}"}


@app.get("/admin")
@authorize(["admin"])
@inject
async def admin_endpoint(service:Service=deps(Service)):
    service()
    return {"message": "Zona admin"}


@app.get("/another-private")
async def another_private_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Otra ruta privada para {principal.username}"}


@app.get("/user-only")
@authorize(["user", "admin"])
async def user_only_endpoint():
    principal = principal_ctx.get()
    return {"message": f"Solo usuarios y admins: {principal.username}"}


@app.post("/create-something")
async def create_something():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Algo creado por {principal.username}"}


@app.get("/manual-security", dependencies=[Security(security_scheme)])
async def manual_security_endpoint():
    principal = principal_ctx.get()
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"message": f"Ruta con seguridad manual para {principal.username}"}


# Limpiar exception handlers por defecto para usar nuestro middleware



if __name__ == "__main__":    
    import uvicorn
    uvicorn.run("authorization:app", host="0.0.0.0", port=8081, reload=True)
