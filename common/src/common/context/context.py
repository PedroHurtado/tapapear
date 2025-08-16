from pydantic import BaseModel, Field
from typing import Dict, Any, FrozenSet
import threading

_thread_local = threading.local()

DOCS_PATHS: set[tuple[str, str]] = {
    ("/openapi.json", "GET"),
    ("/openapi.json", "HEAD"),
    ("/docs", "GET"),
    ("/docs", "HEAD"),
    ("/docs/oauth2-redirect", "GET"),
    ("/docs/oauth2-redirect", "HEAD"),
    ("/redoc", "GET"),
    ("/redoc", "HEAD"),
}

class Context(BaseModel):   
    component_registry: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  
    allow_anonymous_routes: set[tuple[str, str]] = Field(default_factory=set)
    authorize_routes: set[tuple[str, str]] = Field(default_factory=set)
    docs_path: FrozenSet[tuple[str, str]] = Field(default_factory=lambda: frozenset(DOCS_PATHS))
    
def _set_app_context(context: Context) -> Context:    
    _thread_local.context = context
    return context

def get_app_context() -> Context:
    if not hasattr(_thread_local, 'context'):
        _set_app_context(Context())
    return _thread_local.context