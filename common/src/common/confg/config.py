from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel
import yaml


class FirestoreConfig(BaseModel):
    database: str = "(default)"
    credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"


class EnvConfig(BaseModel):
    debug: bool
    reload: bool
    log_level: str
    firestore: FirestoreConfig
    allowed_hosts: Optional[List[str]] = None


class OpenApiConfig(BaseModel):
    title: str
    version: str
    openapi_version: str = "3.1.0"
    summary: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[Dict[str, Any]]] = None
    servers: Optional[List[Dict[str, Union[str, Any]]]] = None
    terms_of_service: Optional[str] = None
    contact: Optional[Dict[str, Union[str, Any]]] = None
    license_info: Optional[Dict[str, Union[str, Any]]] = None
    separate_input_output_schemas: bool = True


class Config(BaseModel):
    name: str
    openapi: OpenApiConfig
    features: str
    security: bool
    middlewares: List[str]
    desarrollo: EnvConfig
    produccion: EnvConfig


def load_config(path: str) -> Config:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return Config(**data)
