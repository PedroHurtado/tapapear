from .errormiddelware import ErrorMiddleware
from .authmiddelware import AuthMiddleware
from fastapi.middleware.cors import CORSMiddleware

SUPPORT_MIDDELWARES = {
    "ErrorMiddleware": ErrorMiddleware,
    "AuthMiddleware": AuthMiddleware,
    "CORSMiddleware": CORSMiddleware,
}
__all__ = ["ErrorMiddleware", "SUPPORT_MIDDELWARES"]
