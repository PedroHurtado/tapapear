from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel, Field
from pathlib import Path
from common.ioc import component, ProviderType
from common.util import get_path
from dotenv import load_dotenv
import os
import yaml





config: Optional["Config"] = None


load_dotenv(get_path(".env"))
APP_ENV = os.getenv("APP_ENV", "production")


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
    credential_path:Optional[str] = None
    credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"


class EnvConfig(BaseModel):
    openapi:bool    
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


def load_config(path: Optional[str] = None) -> "Config":
    global config
    if config is None:
        if path is None:
            path = get_path("config.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Determinar entorno activo según APP_ENV
        active_env_name = APP_ENV  # ya cargado con load_dotenv
        env_data = data.get(active_env_name, {})

        # Crear la Config con solo la env activa
        env_config = EnvConfig(**env_data)

        # Filtrar development/production del diccionario original
        filtered_data = {
            k: v for k, v in data.items() if k not in ("development", "production")
        }
        filtered_data["env"] = env_config

        config = Config(**filtered_data)

    return config


def _load_config():
    return load_config()


@component(provider_type=ProviderType.FACTORY, factory=_load_config)
class Config(BaseModel):
    name: str
    openapi: OpenApiConfig
    features: str
    port: int = 8080
    middlewares: List[Middlewares] = []
    env: EnvConfig  # solo la env activa
