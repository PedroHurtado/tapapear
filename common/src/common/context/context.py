from pydantic import BaseModel,Field
from typing import Dict,Any
import threading

_thread_local = threading.local()

class Context(BaseModel):   
    component_registry: Dict[str, Dict[str, Any]] = Field(default_factory=dict)  


def set_app_context(context: Context)->Context:    
    _thread_local.context = context
    return context

def get_app_context() -> Context:
    if not hasattr(_thread_local, 'context'):
        raise RuntimeError("No app context set for current thread")
    return _thread_local.context
    