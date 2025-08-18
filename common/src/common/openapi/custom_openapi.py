from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from common.middelwares import AuthMiddleware
from common.context import context
from common.confg import config,Config


def create_custom_openapi(app: FastAPI, config:Config=config()):
    """
    Crea una función personalizada de OpenAPI para la aplicación FastAPI dada.
    
    Args:
        app: Instancia de FastAPI
        
    Returns:
        Función personalizada de OpenAPI que FastAPI invocará cuando sea necesario
    """
    def custom_openapi():        

        # FastAPI cachea el esquema, si ya existe lo devuelve
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            routes=app.routes,
            **app.config.openapi.model_dump(exclude={"tags"}),
            tags=[
                {"name": name, "description": tag.description}
                for name, tag in app.config.openapi.tags.items()    
            ]
        )

        has_auth_middleware = any(
            hasattr(middleware, 'cls') and middleware.cls is AuthMiddleware
            for middleware in app.user_middleware
        )

        def ensure_validation_schemas():
            """Asegura que ValidationError esté definido."""
            schemas = openapi_schema["components"].setdefault("schemas", {})

            if "ValidationError" not in schemas:
                schemas["ValidationError"] = {
                    "type": "object",
                    "title": "ValidationError",
                    "properties": {
                        "loc": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "integer"}
                                ]
                            }
                        },
                        "msg": {"type": "string"},
                        "type": {"type": "string"}
                    },
                    "required": ["loc", "msg", "type"],
                    "example": {
                        "loc": ["body", "email"],
                        "msg": "field required",
                        "type": "value_error.missing"
                    }
                }

        openapi_schema.setdefault("components", {})

        if has_auth_middleware:
            openapi_schema["components"]["securitySchemes"] = {
                "HTTPBearer": {"type": "http", "scheme": "bearer"}
            }

            ensure_validation_schemas()

            openapi_schema["components"]["schemas"]["ErrorResponse"] = {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "status": {"type": "integer"},
                    "error": {"type": "string"},
                    "exception": {"type": "string", "nullable": True},
                    "message": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/ValidationError"}
                            }
                        ],
                        "description": "Error message - either a simple string or array of validation errors"
                    },
                    "path": {"type": "string"},
                },
                "required": ["timestamp", "status", "error", "message", "path"]
            }

            error_responses = {
                "UnauthorizedError": {
                    "description": "Access token is missing or invalid",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
                },
                "ForbiddenError": {
                    "description": "Insufficient permissions",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
                },
                "ValidationError": {
                    "description": "Validation error",
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
                },
            }
            openapi_schema["components"].setdefault("responses", {}).update(error_responses)

        else:
            ensure_validation_schemas()

            openapi_schema["components"]["schemas"]["ErrorResponse"] = {
                "type": "object",
                "properties": {
                    "timestamp": {"type": "string", "format": "date-time"},
                    "status": {"type": "integer"},
                    "error": {"type": "string"},
                    "exception": {"type": "string", "nullable": True},
                    "message": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/ValidationError"}
                            }
                        ]
                    },
                    "path": {"type": "string"},
                },
                "required": ["timestamp", "status", "error", "message", "path"]
            }

            if "HTTPValidationError" in openapi_schema["components"]["schemas"]:
                del openapi_schema["components"]["schemas"]["HTTPValidationError"]

            openapi_schema["components"].setdefault("responses", {})["ValidationError"] = {
                "description": "Validation error",
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
            }

        for path, path_item in openapi_schema["paths"].items():
            if any((path, m) in context.docs_path for m in ["GET", "HEAD"]):
                continue
            for method, operation in path_item.items():
                if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"}:
                    route_key = (path, method.upper())
                    if "responses" in operation and "422" in operation["responses"]:
                        operation["responses"]["422"] = {"$ref": "#/components/responses/ValidationError"}
                    if route_key not in context.allow_anonymous_routes and has_auth_middleware:
                        operation["security"] = [{"HTTPBearer": []}]
                        operation.setdefault("responses", {})
                        operation["responses"]["401"] = {"$ref": "#/components/responses/UnauthorizedError"}
                        if route_key in context.authorize_routes:
                            operation["responses"]["403"] = {"$ref": "#/components/responses/ForbiddenError"}

        if "components" in openapi_schema and "schemas" in openapi_schema["components"]:
            if "HTTPValidationError" in openapi_schema["components"]["schemas"]:
                del openapi_schema["components"]["schemas"]["HTTPValidationError"]
            
            schemas = openapi_schema["components"]["schemas"]
            reordered = {k: v for k, v in schemas.items()
                         if k not in ("ErrorResponse", "ValidationError")}
            for key in ("ErrorResponse", "ValidationError"):
                if key in schemas:
                    reordered[key] = schemas[key]
            openapi_schema["components"]["schemas"] = reordered

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    return custom_openapi


# Uso de la función
def setup_custom_openapi(app: FastAPI) -> None:
    """
    Configura el esquema OpenAPI personalizado para la aplicación.
    FastAPI invocará esta función cuando necesite generar el esquema OpenAPI.
    
    Args:
        app: Instancia de FastAPI a configurar
    """
    app.openapi = create_custom_openapi(app)


# Ejemplo de uso:
# app = FastAPI(title="Mi API", version="1.0.0")
# 
# # FastAPI invocará la función cuando sea necesario (ej: al acceder a /docs)
# app.openapi = create_custom_openapi(app,config)
# 
# # O usando la función helper:
# setup_custom_openapi(app,config)