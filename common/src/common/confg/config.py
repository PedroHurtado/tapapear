from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel,Field
from pathlib import Path
import yaml
import sys

class Middlewares(BaseModel):
    class_: str = Field(..., alias="class")  
    options: Dict[str, Any] = {}

    class Config:
        validate_by_name = True

class TagConfig(BaseModel):
    prefix: str
    description: Optional[str] = None

class FirestoreConfig(BaseModel):
    database: str = "(default)"
    credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"


class EnvConfig(BaseModel):
    debug: bool
    reload: bool
    log_level: str
    firestore: Optional[FirestoreConfig] = None
    allowed_hosts: Optional[List[str]] = None


class OpenApiConfig(BaseModel):
    title: str
    version: str
    openapi_version: str = "3.1.0"
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: Dict[str, TagConfig]
    servers: Optional[List[Dict[str, Union[str, Any]]]] = None
    terms_of_service: Optional[str] = None
    contact: Optional[Dict[str, Union[str, Any]]] = None
    license_info: Optional[Dict[str, Union[str, Any]]] = None
    separate_input_output_schemas: bool = True


class Config(BaseModel):
    name: str
    openapi: OpenApiConfig
    features: str
    port:int    
    middlewares: List[Middlewares] = []
    desarrollo: EnvConfig
    produccion: EnvConfig





# Variable global

config:Optional[Config] = None

def load_config(path: Optional[str] = None) -> Config:
    """
    Carga el config.yaml automáticamente si no está cargado aún.
    - Si `path` no se pasa, busca el config.yaml en la misma carpeta
      que el script principal (sys.argv[0]).
    """
    global config
    if config is None:
        if path is None:
            # Ruta del script principal (main.py del microservicio)
            main_dir = Path(sys.argv[0]).resolve().parent
            path = main_dir / "config.yaml"

        with open(path, "r",encoding="utf-8") as f:
            data = yaml.safe_load(f)
        config = Config(**data)
    return config

    








