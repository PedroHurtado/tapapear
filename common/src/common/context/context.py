from pydantic import BaseModel, Field
from typing import Dict, Any, FrozenSet,Type, List

DOCS_PATHS: set[tuple[str, str]] = {
    ("/openapi.json", "GET"),
    ("/openapi.json", "HEAD"),
    ("/docs", "GET"),
    ("/docs", "HEAD"),
    ("/docs/oauth2-redirect", "GET"),
    ("/docs/oauth2-redirect", "HEAD"),
    ("/redoc", "GET"),
    ("/redoc", "HEAD"),
    ("/health", "GET"),
    ("/health", "HEAD"),
}

class Context(BaseModel):   
    component_registry: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  
    allow_anonymous_routes: set[tuple[str, str]] = Field(default_factory=set)
    authorize_routes: set[tuple[str, str]] = Field(default_factory=set)
    docs_path: FrozenSet[tuple[str, str]] = Field(default_factory=lambda: frozenset(DOCS_PATHS))
    modules:set[str] = Field(default_factory=set)
    commands:Dict[Type[Any], Type] = Field(default_factory=dict)
    notifications: Dict[Type[Any], List[Type[Any]]] = Field(default_factory=dict)
    
context = Context()


