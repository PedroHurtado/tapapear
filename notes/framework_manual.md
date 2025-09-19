# Manual del Framework FastAPI DDD

## Tabla de Contenidos

1. [Introducción](#introducción)
2. [Instalación y Configuración](#instalación-y-configuración)
3. [Arquitectura del Framework](#arquitectura-del-framework)
4. [Configuración](#configuración)
5. [Domain Driven Design](#domain-driven-design)
6. [Inyección de Dependencias (IoC)](#inyección-de-dependencias-ioc)
7. [Mediator Pattern](#mediator-pattern)
8. [Repositorios e Infraestructura](#repositorios-e-infraestructura)
9. [Cliente HTTP](#cliente-http)
10. [Seguridad y Autenticación](#seguridad-y-autenticación)
11. [Middlewares](#middlewares)
12. [OpenAPI y Documentación](#openapi-y-documentación)
13. [Manejo de Errores](#manejo-de-errores)
14. [Telemetría y Observabilidad](#telemetría-y-observabilidad)
15. [Ejemplo Completo](#ejemplo-completo)

---

## Introducción

Este framework está diseñado para crear aplicaciones FastAPI siguiendo principios de Domain Driven Design (DDD), con soporte completo para:

- **Arquitectura limpia** con separación clara entre capas
- **Inyección de dependencias** automática
- **Patrón Mediator** para Commands/Queries
- **Repositorio y Unit of Work** patterns
- **Integración nativa con Firestore**
- **Cliente HTTP avanzado** con retry y telemetría
- **OpenTelemetry** para observabilidad
- **Sistema de configuración** flexible
- **Middlewares personalizados**
- **Documentación OpenAPI** mejorada

---

## Instalación y Configuración

### Estructura del Proyecto

```
my-project/
├── common/                 # Framework base
├── features/              # Features de la aplicación
│   └── users/
│       ├── commands/
│       ├── queries/
│       ├── models/
│       └── __init__.py
├── config.yaml           # Configuración
├── credentials.json       # Credenciales Firestore
└── main.py               # Punto de entrada
```

### Configuración Básica

Crea un archivo `config.yaml`:

```yaml
env:
  reload: true
  openapi: true
  firestore:
    credential_path: "credentials.json"
    database: "(default)"

port: 8080

openapi:
  title: "Mi API"
  description: "API construida con el framework DDD"
  version: "1.0.0"
  tags:
    users:
      description: "Gestión de usuarios"
      prefix: "/api/users"

middlewares:
  - class_: "ErrorMiddleware"
    options: {}
  - class_: "AuthMiddleware"
    options: {}
  - class_: "CORSMiddleware"
    options:
      allow_origins: ["*"]
      allow_methods: ["*"]
      allow_headers: ["*"]

features: "features"
```

### Punto de Entrada

Crea `main.py`:

```python
from common.server import AppBuilder

def main():
    app_builder = AppBuilder()
    return app_builder.build().app

app = main()

if __name__ == "__main__":
    app_builder = AppBuilder()
    app_builder.build().run()
```

---

## Arquitectura del Framework

### Principios de Diseño

El framework sigue estos principios arquitectónicos:

1. **Separation of Concerns**: Cada capa tiene una responsabilidad específica
2. **Dependency Inversion**: Las dependencias siempre apuntan hacia adentro
3. **Command Query Responsibility Segregation (CQRS)**: Separación entre comandos y consultas
4. **Domain Events**: Comunicación desacoplada entre agregados

### Capas de la Arquitectura

```
┌─────────────────────────────────────┐
│            Presentation             │  ← FastAPI Routes, Controllers
├─────────────────────────────────────┤
│            Application              │  ← Commands, Queries, Handlers
├─────────────────────────────────────┤
│              Domain                 │  ← Entities, Value Objects, Events
├─────────────────────────────────────┤
│           Infrastructure            │  ← Repositories, External APIs
└─────────────────────────────────────┘
```

---

## Configuración

### Sistema de Configuración

El framework utiliza un sistema de configuración basado en YAML con validación Pydantic:

```python
from common.confg import Config, config

# Obtener configuración global
app_config = config()

# Acceder a valores
database_name = app_config.env.firestore.database
api_title = app_config.openapi.title
```

### Configuración de Entorno

```yaml
env:
  reload: true              # Recarga automática en desarrollo
  openapi: true            # Habilitar documentación OpenAPI
  firestore:
    credential_path: "path/to/credentials.json"
    database: "(default)"
```

### Configuración de Features

```yaml
openapi:
  tags:
    users:
      description: "User management"
      prefix: "/api/v1/users"
    orders:
      description: "Order management" 
      prefix: "/api/v1/orders"
```

---

## Domain Driven Design

### Entidades Base

```python
from common.domain import BaseEntity
from common.util import ID

class User(BaseEntity):
    def __init__(self, id: ID, name: str, email: str):
        super().__init__(id)
        self.name = name
        self.email = email
    
    def change_email(self, new_email: str):
        # Lógica de dominio
        if not self._is_valid_email(new_email):
            raise ValueError("Invalid email")
        
        old_email = self.email
        self.email = new_email
        
        # Emitir evento de dominio
        self.add_event(UserEmailChanged(
            aggregate="User",
            aggregate_id=self.id,
            data={"old_email": old_email, "new_email": new_email}
        ))
```

### Value Objects

```python
from common.domain import ValueObject

class Email(ValueObject):
    value: str
    
    def __init__(self, value: str):
        if not self._is_valid(value):
            raise ValueError("Invalid email format")
        super().__init__(value=value)
    
    def _is_valid(self, email: str) -> bool:
        # Validación del email
        return "@" in email and "." in email
```

### Domain Events

```python
from common.domain.events import DomainEvent
from common.util import ID
from uuid import UUID

class UserEmailChanged(DomainEvent):
    aggregate: str = "User"
    aggregate_id: UUID
    data: dict
```

### Event Containers

```python
from common.domain import DomainEventContainer

class User(BaseEntity, DomainEventContainer):
    def __init__(self, id: ID, name: str, email: str):
        BaseEntity.__init__(self, id)
        DomainEventContainer.__init__(self)
        self.name = name
        self.email = email
    
    def change_email(self, new_email: str):
        # ... lógica ...
        self.add_event(UserEmailChanged(...))
```

---

## Inyección de Dependencias (IoC)

### Registro de Componentes

```python
from common.ioc import component, ProviderType

# Registro como Singleton (por defecto)
@component
class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

# Registro como Factory
@component(provider_type=ProviderType.FACTORY)
class EmailService:
    def send_email(self, to: str, subject: str, body: str):
        pass

# Registro manual
component(UserRepository, provider_type=ProviderType.SINGLETON)
```

### Inyección de Dependencias

```python
from common.ioc import inject, deps

@inject
class UserController:
    def __init__(self, service: UserService = deps(UserService)):
        self.service = service

# O en funciones
@inject
async def get_user(
    user_id: str,
    service: UserService = deps(UserService)
):
    return await service.get_user(user_id)
```

### Tipos de Proveedores

1. **SINGLETON**: Una instancia para toda la aplicación
2. **FACTORY**: Nueva instancia en cada inyección
3. **RESOURCE**: Para recursos que necesitan cleanup
4. **OBJECT**: Para instancias pre-creadas
5. **LIST**: Para colecciones de implementaciones

```python
# Lista de implementaciones
@component
class EmailNotifier(NotificationHandler):
    pass

@component  
class SMSNotifier(NotificationHandler):
    pass

# El framework automáticamente creará List[NotificationHandler]
@inject
class NotificationService:
    def __init__(self, handlers: List[NotificationHandler] = deps(List[NotificationHandler])):
        self.handlers = handlers
```

---

## Mediator Pattern

### Commands

```python
from common.mediator import Command
from common.openapi import FeatureModel

class CreateUserCommand(Command, FeatureModel):
    name: str
    email: str
    age: int
```

### Command Handlers

```python
from common.mediator import CommandHadler
from common.ioc import component

@component
class CreateUserHandler(CommandHadler[CreateUserCommand]):
    def __init__(self, repository: UserRepository):
        self.repository = repository
    
    async def handler(self, command: CreateUserCommand) -> str:
        user = User(
            id=get_id(),
            name=command.name,
            email=command.email
        )
        
        await self.repository.create(user)
        return str(user.id)
```

### Uso del Mediator

```python
from fastapi import APIRouter
from common.mediator import Mediator
from common.ioc import inject, deps

router = APIRouter()

@router.post("/users")
@inject
async def create_user(
    command: CreateUserCommand,
    mediator: Mediator = deps(Mediator)
):
    user_id = await mediator.send(command)
    return {"id": user_id}
```

### Notification Handlers (Domain Events)

```python
from common.mediator import NotificationHandler
from common.ioc import component

@component
class UserEmailChangedHandler(NotificationHandler[UserEmailChanged]):
    def __init__(self, email_service: EmailService):
        self.email_service = email_service
    
    async def handler(self, event: UserEmailChanged) -> None:
        # Enviar email de confirmación
        await self.email_service.send_confirmation_email(
            event.data["new_email"]
        )
```

### Pipelines

```python
from common.mediator import CommandPipeLine, PipelineContext, ordered

@component
@ordered(1)  # Orden de ejecución
class ValidationPipeline(CommandPipeLine):
    async def handler(self, context: PipelineContext, next_handler) -> Any:
        # Pre-procesamiento
        print(f"Validating command: {type(context.message).__name__}")
        
        # Ejecutar siguiente handler
        result = await next_handler()
        
        # Post-procesamiento
        print("Command executed successfully")
        return result

# Aplicar pipeline específico a un handler
@pipelines(ValidationPipeline)
@component
class CreateUserHandler(CommandHadler[CreateUserCommand]):
    # ... implementación
```

---

## Repositorios e Infraestructura

### Documentos de Firestore

```python
from common.infrastructure import Document, id, reference, collection
from typing import List

class User(Document):
    name: str
    email: str
    
class Profile(Document):
    user_id: UUID = reference("users")  # Referencia a users collection
    bio: str
    avatar_url: Optional[str] = None

class Order(Document):
    user_id: UUID = reference("users")
    items: List[OrderItem] = collection("items")  # Subcolección
    total: float
```

### Repositorios

```python
from common.infrastructure import RepositoryFirestore
from common.ioc import component

@component
class UserRepository(RepositoryFirestore[User]):
    # Hereda automáticamente: create, update, delete, get, find_by_field
    pass

# Repositorio personalizado
@component
class OrderRepository(RepositoryFirestore[Order]):
    async def find_by_user(self, user_id: UUID) -> List[Order]:
        return await self.find_by_field("user_id", user_id)
    
    async def find_pending_orders(self) -> List[Order]:
        return await self.find_by_field("status", "pending")
```

### Repositorios Domain (Patrón Repository)

```python
from common.infrastructure.repository import Repository, AbstractRepository
from common.mapper import mapper_class

# Mapeo entre entidades de dominio e infraestructura
@mapper_class(source=domain.User, target=UserDocument)
class UserMapper:
    pass

@component
class UserDomainRepository(AbstractRepository[UserRepository], Repository[domain.User]):
    # Automáticamente obtiene: create, get, update, delete
    # Con mapeo automático entre domain.User y UserDocument
    pass
```

### Unit of Work y Change Tracking

```python
from common.infrastructure.unit_of_work import (
    ChangeTracker, 
    ChangeType, 
    FirestoreDialect,
    get_change_tracker
)

# En un handler
async def handle_complex_operation(self):
    dialect = FirestoreDialect(db, transaction)
    tracker = ChangeTracker(dialect)
    
    # Trackear cambios
    user = await self.user_repo.get(user_id)
    tracker.track_entity(user, ChangeType.MODIFIED)
    
    user.change_email("new@email.com")
    
    order = Order(...)
    tracker.track_entity(order, ChangeType.ADDED)
    
    # Ejecutar todos los cambios en una transacción
    tracker.save_changes()
```

---

## Cliente HTTP

### Configuración Básica

```python
from common.http import HttpClient
from pydantic import BaseModel

client = HttpClient(
    base_url="https://api.ejemplo.com",
    max_retries=3,
    backoff_factor=1.0
)

class UserDto(BaseModel):
    name: str
    email: str

class CreateUserRequest(BaseModel):
    name: str
    email: str
```

### Métodos HTTP

```python
@client.get("/users/{user_id}")
async def get_user(self, user_id: str) -> UserDto:
    pass

@client.post("/users")
async def create_user(self, body: CreateUserRequest) -> UserDto:
    pass

@client.put("/users/{user_id}")
async def update_user(self, user_id: str, body: CreateUserRequest) -> UserDto:
    pass

@client.delete("/users/{user_id}")
async def delete_user(self, user_id: str) -> None:
    pass
```

### Query Parameters

```python
class SearchQuery(BaseModel):
    q: str
    limit: int = 10
    offset: int = 0

@client.get("/users/search")
async def search_users(self, query: SearchQuery) -> List[UserDto]:
    pass
```

### Formularios

```python
class LoginForm(BaseModel):
    username: str
    password: str

@client.post("/auth/login")
async def login(self, form: LoginForm) -> TokenResponse:
    pass
```

### Archivos

```python
from common.http import File

class UploadRequest(BaseModel):
    file: File
    description: str

@client.post("/upload")
async def upload_file(self, form_data: UploadRequest) -> UploadResponse:
    pass

# Uso
file_content = File(
    content=file_bytes,
    filename="document.pdf",
    content_type="application/pdf"
)

request = UploadRequest(file=file_content, description="Important document")
response = await client.upload_file(request)
```

### Headers y Autenticación

```python
from common.http import jwt_token_var

# Configurar token en contexto
jwt_token_var.set("your-jwt-token")

# O usar headers personalizados
@client.post("/protected", headers={"X-API-Key": "secret"})
async def protected_endpoint(self) -> dict:
    pass

# Permitir acceso anónimo
@client.get("/public", allow_anonymous=True)
async def public_endpoint(self) -> dict:
    pass
```

---

## Seguridad y Autenticación

### Configuración de Seguridad

```python
from common.security import Principal, allow_anonymous, authorize

# Modelo del usuario autenticado
@component
class CustomPrincipal(Principal):
    tenant_id: Optional[str] = None
    permissions: List[str] = []
```

### Rutas Protegidas

```python
from fastapi import APIRouter
from common.security import authorize, allow_anonymous

router = APIRouter()

# Ruta que requiere autenticación
@router.get("/protected")
async def protected_route():
    return {"message": "You are authenticated"}

# Ruta que requiere roles específicos
@router.get("/admin")
@authorize(roles=["admin", "super_admin"])
async def admin_route():
    return {"message": "Admin access granted"}

# Ruta pública
@router.get("/public")
@allow_anonymous
async def public_route():
    return {"message": "Public access"}
```

### Acceso al Principal

```python
from common.security import Principal
from common.ioc import inject, deps

@router.get("/me")
@inject
async def get_current_user(principal: Principal = deps(Principal)):
    return {
        "id": principal.id,
        "username": principal.username,
        "email": principal.email,
        "role": principal.role
    }
```

---

## Middlewares

### Middleware de Errores

El `ErrorMiddleware` proporciona manejo uniforme de errores:

```python
# Configuración en config.yaml
middlewares:
  - class_: "ErrorMiddleware"
    options: {}
```

Respuesta de error estandarizada:

```json
{
  "timestamp": "2023-10-01T12:00:00.000Z",
  "status": 400,
  "error": "Bad Request",
  "exception": "ValidationException",
  "message": "Invalid input data",
  "path": "/api/users"
}
```

### Middleware de Autenticación

```python
# Configuración
middlewares:
  - class_: "AuthMiddleware"
    options: {}
```

El middleware:
- Extrae tokens JWT del header `Authorization`
- Valida rutas protegidas vs. públicas
- Inyecta el `Principal` en el contexto

### CORS

```python
middlewares:
  - class_: "CORSMiddleware"
    options:
      allow_origins: ["http://localhost:3000"]
      allow_methods: ["GET", "POST", "PUT", "DELETE"]
      allow_headers: ["*"]
      allow_credentials: true
```

---

## OpenAPI y Documentación

### Configuración OpenAPI

```yaml
openapi:
  title: "Mi API"
  description: "API construida con el framework"
  version: "1.0.0"
  contact:
    name: "Equipo de Desarrollo"
    email: "dev@company.com"
  license:
    name: "MIT"
  tags:
    users:
      description: "Gestión de usuarios"
      prefix: "/api/v1/users"
```

### Responses de Error

```python
from common.openapi import build_error_responses

@router.post(
    "/users",
    responses=build_error_responses(400, 409)  # Bad Request, Conflict
)
async def create_user(command: CreateUserCommand):
    pass
```

### Feature Models

```python
from common.openapi import FeatureModel

# Automáticamente genera nombres bonitos para OpenAPI
class CreateUserCommand(FeatureModel):
    name: str
    email: str
    
# Se mostrará como "UsersCreateUserCommand" en la documentación
```

---

## Manejo de Errores

### Excepciones de Dominio

```python
from common.exceptions import (
    ConflictDomainException,
    NotFoundDomainException,
    BadRequestDomainException
)

# En un handler
async def handler(self, command: CreateUserCommand) -> str:
    existing_user = await self.repository.find_by_email(command.email)
    if existing_user:
        raise ConflictDomainException("User with this email already exists")
    
    user = User(...)
    await self.repository.create(user)
    return str(user.id)
```

### Excepciones HTTP

```python
from common.exceptions import HttpApiRetryException, HttpApiStatusError

# En un cliente HTTP
try:
    response = await external_api.get_user(user_id)
except httpx.HTTPStatusError as e:
    if e.response.status_code >= 500:
        raise HttpApiRetryException("External service unavailable", cause=e)
    else:
        raise HttpApiStatusError("External API error", e.response.status_code, cause=e)
```

### Respuestas de Error

Todas las excepciones se convierten automáticamente a:

```json
{
  "timestamp": "2023-10-01T12:00:00.000Z",
  "status": 409,
  "error": "Conflict",
  "exception": "ConflictDomainException",
  "message": "User with this email already exists",
  "path": "/api/users"
}
```

---

## Telemetría y Observabilidad

### OpenTelemetry Automático

El framework incluye trazas automáticas para:

- **Mediator**: Commands y Notification handlers
- **Repositories**: Operaciones CRUD
- **HTTP Client**: Requests, retries, parsing
- **Firestore**: Operaciones de base de datos

### Atributos de Traza

```python
# Los spans incluyen automáticamente:
{
  "mediator.command.type": "CreateUserCommand",
  "mediator.command.handler": "CreateUserHandler",
  "repository.operation": "create",
  "repository.entity_type": "User",
  "httpclient.method": "POST",
  "httpclient.url": "https://api.example.com/users",
  "db.system": "firestore",
  "db.collection.name": "users"
}
```

### Configuración de Telemetría

```python
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Configurar Jaeger
tracer_provider = TracerProvider()
trace.set_tracer_provider(tracer_provider)

jaeger_exporter = JaegerExporter(
    agent_host_name="localhost",
    agent_port=14268,
)

tracer_provider.add_span_processor(
    BatchSpanProcessor(jaeger_exporter)
)
```

---

## Ejemplo Completo

### 1. Estructura del Feature

```
features/{feature_name}/
├── __init__.py
├── models/
│   └── __init__.py
├── commands/
│   └── __init__.py
├── queries/
│   └── __init__.py
├── events/
│   └── __init__.py
├── infrastructure/
│   ├── __init__.py
│   ├── repositories/
│   │   └── __init__.py
│   └── external/
│       └── __init__.py
└── tests/
    └── __init__.py
```

### 2. Domain Model

```python
# features/users/models/user.py
from common.domain import BaseEntity, DomainEventContainer
from common.util import ID

class User(BaseEntity, DomainEventContainer):
    def __init__(self, id: ID, name: str, email: str):
        BaseEntity.__init__(self, id)
        DomainEventContainer.__init__(self)
        self.name = name
        self.email = email
    
    def change_email(self, new_email: str):
        if not self._is_valid_email(new_email):
            raise ValueError("Invalid email")
        
        old_email = self.email
        self.email = new_email
        
        self.add_event(UserEmailChanged(
            aggregate="User",
            aggregate_id=self.id,
            data={"old_email": old_email, "new_email": new_email}
        ))
    
    def _is_valid_email(self, email: str) -> bool:
        return "@" in email and "." in email
```

### 3. Infrastructure Document

```python
# features/users/models/user_document.py
from common.infrastructure import Document
from typing import Optional

class UserDocument(Document):
    name: str
    email: str
    is_active: bool = True
    tenant_id: Optional[str] = None
```

### 4. Repository

```python
# features/users/models/__init__.py
from common.infrastructure import RepositoryFirestore, AbstractRepository, Repository
from common.ioc import component
from common.mapper import mapper_class
from .user import User
from .user_document import UserDocument

# Mapeo automático entre domain y document
@mapper_class(source=User, target=UserDocument)
class UserMapper:
    pass

# Repository de infraestructura
@component
class UserFirestoreRepository(RepositoryFirestore[UserDocument]):
    async def find_by_email(self, email: str) -> Optional[UserDocument]:
        results = await self.find_by_field("email", email, limit=1)
        return results[0] if results else None

# Repository de dominio
@component  
class UserRepository(AbstractRepository[UserFirestoreRepository], Repository[User]):
    async def find_by_email(self, email: str) -> Optional[User]:
        result = await self._repo.find_by_email(email)
        return self._mapper.map(result) if result else None
```

### 5. Commands

```python
# features/users/commands/create_user.py
from common.mediator import Command, CommandHadler
from common.openapi import FeatureModel
from common.ioc import component, inject, deps
from ..models import User, UserRepository
from common.util import get_id

class CreateUserCommand(Command, FeatureModel):
    name: str
    email: str

@component
class CreateUserHandler(CommandHadler[CreateUserCommand]):
    @inject
    def __init__(self, repository: UserRepository = deps(UserRepository)):
        self.repository = repository
    
    async def handler(self, command: CreateUserCommand) -> str:
        # Verificar que no existe usuario con ese email
        existing = await self.repository.find_by_email(command.email)
        if existing:
            raise ConflictDomainException("User with this email already exists")
        
        # Crear usuario
        user = User(
            id=get_id(),
            name=command.name,
            email=command.email
        )
        
        # Guardar (automáticamente publica domain events)
        await self.repository.create(user)
        
        return str(user.id)
```

### 6. Queries

```python
# features/users/queries/get_user.py
from common.mediator import Command, CommandHadler
from common.openapi import FeatureModel
from common.ioc import component, inject, deps
from common.exceptions import NotFoundDomainException
from ..models import User, UserRepository
from uuid import UUID

class GetUserQuery(Command, FeatureModel):
    user_id: UUID

class UserResponse(FeatureModel):
    id: UUID
    name: str
    email: str

@component
class GetUserHandler(CommandHadler[GetUserQuery]):
    @inject
    def __init__(self, repository: UserRepository = deps(UserRepository)):
        self.repository = repository
    
    async def handler(self, query: GetUserQuery) -> UserResponse:
        user = await self.repository.get(
            query.user_id, 
            "User not found"
        )
        
        return UserResponse(
            id=user.id,
            name=user.name,
            email=user.email
        )
```

### 7. Event Handlers

```python
# features/users/events.py
from common.domain.events import DomainEvent
from common.mediator import NotificationHandler
from common.ioc import component
from uuid import UUID

class UserEmailChanged(DomainEvent):
    aggregate: str = "User"
    aggregate_id: UUID
    data: dict

@component
class UserEmailChangedHandler(NotificationHandler[UserEmailChanged]):
    def __init__(self, email_service: EmailService):
        self.email_service = email_service
    
    async def handler(self, event: UserEmailChanged) -> None:
        new_email = event.data["new_email"]
        await self.email_service.send_confirmation_email(new_email)
```

### 8. API Routes

```python
# features/users/__init__.py
from fastapi import APIRouter
from common.server import build_router
from common.mediator import Mediator
from common.ioc import inject, deps
from common.openapi import build_error_responses
from .commands.create_user import CreateUserCommand
from .queries.get_user import GetUserQuery, UserResponse
from uuid import UUID

router = build_router("users")

@router.post(
    "/",
    response_model=dict,
    responses=build_error_responses(400, 409)
)
@inject
async def create_user(
    command: CreateUserCommand,
    mediator: Mediator = deps(Mediator)
) -> dict:
    user_id = await mediator.send(command)
    return {"id": user_id}

@router.get(
    "/{user_id}",
    response_model=UserResponse,
    responses=build_error_responses(404)
)
@inject  
async def get_user(
    user_id: UUID,
    mediator: Mediator = deps(Mediator)
) -> UserResponse:
    query = GetUserQuery(user_id=user_id)
    return await mediator.send(query)
```

### 9. Configuración Final

```yaml
# config.yaml
env:
  reload: true
  openapi: true
  firestore:
    credential_path: "credentials.json"
    database: "(default)"

port: 8080

openapi:
  title: "Users API"
  description: "Complete user management API"
  version: "1.0.0"
  tags:
    users:
      description: "User management operations"
      prefix: "/api/v1/users"

middlewares:
  - class_: "ErrorMiddleware"
    options: {}
  - class_: "AuthMiddleware"
    options: {}
  - class_: "CORSMiddleware"
    options:
      allow_origins: ["*"]
      allow_methods: ["*"]
      allow_headers: ["*"]

features: "features"
```

### 10. Aplicación Principal

```python
# main.py
from common.server import AppBuilder

def create_app():
    """Factory function para crear la aplicación"""
    builder = AppBuilder()
    return builder.build().app

# Para desarrollo
app = create_app()

if __name__ == "__main__":
    # Ejecutar servidor de desarrollo
    builder = AppBuilder()
    builder.build().run(port=8080)
```

---

## Características Avanzadas

### Change Tracking y Unit of Work

```python
from common.infrastructure.unit_of_work import (
    ChangeTracker, 
    ChangeType, 
    FirestoreDialect,
    VerboseConsoleDialect  # Para debugging
)

@component
class ComplexBusinessOperationHandler(CommandHadler[ComplexCommand]):
    async def handler(self, command: ComplexCommand):
        # Usar console dialect para debugging
        dialect = VerboseConsoleDialect()
        tracker = ChangeTracker(dialect)
        
        # Operaciones complejas con múltiples entidades
        user = await self.user_repo.get(command.user_id)
        user.update_profile(command.profile_data)
        tracker.track_entity(user, ChangeType.MODIFIED)
        
        # Crear nuevas órdenes
        for item_data in command.items:
            order = Order(...)
            tracker.track_entity(order, ChangeType.ADDED)
        
        # Eliminar órdenes canceladas
        cancelled_orders = await self.order_repo.find_cancelled()
        for order in cancelled_orders:
            tracker.track_entity(order, ChangeType.DELETED)
        
        # Ejecutar todos los cambios de una vez
        tracker.save_changes()
```

### Pipelines Personalizados

```python
from common.mediator import CommandPipeLine, PipelineContext, ordered

@component
@ordered(1)
class AuditPipeline(CommandPipeLine):
    def __init__(self, audit_service: AuditService):
        self.audit_service = audit_service
    
    async def handler(self, context: PipelineContext, next_handler) -> Any:
        command = context.message
        start_time = time.time()
        
        try:
            result = await next_handler()
            
            # Auditar comando exitoso
            await self.audit_service.log_success(
                command_type=type(command).__name__,
                duration=time.time() - start_time,
                user_id=context.get_data("user_id")
            )
            
            return result
            
        except Exception as e:
            # Auditar error
            await self.audit_service.log_error(
                command_type=type(command).__name__,
                error=str(e),
                duration=time.time() - start_time
            )
            raise

@component
@ordered(2)
class CachePipeline(CommandPipeLine):
    def __init__(self, cache_service: CacheService):
        self.cache_service = cache_service
    
    async def handler(self, context: PipelineContext, next_handler) -> Any:
        command = context.message
        cache_key = f"{type(command).__name__}:{hash(str(command.dict()))}"
        
        # Intentar obtener del cache
        cached_result = await self.cache_service.get(cache_key)
        if cached_result:
            return cached_result
        
        # Ejecutar y cachear resultado
        result = await next_handler()
        await self.cache_service.set(cache_key, result, ttl=300)
        
        return result
```

### Integración con APIs Externas

```python
# services/external_apis.py
from common.http import HttpClient, File
from common.ioc import component
from pydantic import BaseModel

@component
class PaymentApiClient(HttpClient):
    def __init__(self):
        super().__init__(
            base_url="https://api.payments.com",
            headers={"X-API-Key": "your-api-key"},
            max_retries=3
        )

class PaymentRequest(BaseModel):
    amount: float
    currency: str
    customer_id: str

class PaymentResponse(BaseModel):
    id: str
    status: str
    amount: float

@PaymentApiClient.post("/payments")
async def create_payment(self, body: PaymentRequest) -> PaymentResponse:
    pass

@PaymentApiClient.get("/payments/{payment_id}")
async def get_payment(self, payment_id: str) -> PaymentResponse:
    pass

# Uso en un handler
@component
class ProcessPaymentHandler(CommandHadler[ProcessPaymentCommand]):
    def __init__(self, payment_client: PaymentApiClient):
        self.payment_client = payment_client
    
    async def handler(self, command: ProcessPaymentCommand) -> str:
        request = PaymentRequest(
            amount=command.amount,
            currency=command.currency,
            customer_id=str(command.user_id)
        )
        
        response = await self.payment_client.create_payment(request)
        
        if response.status != "approved":
            raise BadRequestDomainException("Payment was declined")
        
        return response.id
```

### Subcolecciones de Firestore

```python
from common.infrastructure import Document, collection, reference

class User(Document):
    name: str
    email: str

class Address(Document):
    street: str
    city: str
    country: str

class Order(Document):
    user_id: UUID = reference("users")
    total: float
    # Subcolección de items
    items: List[OrderItem] = collection("items")
    # Subcolección con nombre personalizado
    payments: List[Payment] = collection("order_payments")
    # Subcolección con ID dinámico
    audit_logs: List[AuditLog] = collection("audits/{id}")

class OrderItem(Document):
    product_id: str
    quantity: int
    price: float

# El framework automáticamente:
# - Crea documentos en: orders/{order_id}/items/{item_id}
# - Maneja referencias automáticamente
# - Ordena operaciones por jerarquía
```

### Testing

```python
# tests/test_users.py
import pytest
from unittest.mock import AsyncMock
from features.users.commands.create_user import CreateUserCommand, CreateUserHandler
from features.users.models import UserRepository
from common.exceptions import ConflictDomainException

@pytest.fixture
def mock_repository():
    return AsyncMock(spec=UserRepository)

@pytest.fixture
def handler(mock_repository):
    return CreateUserHandler(repository=mock_repository)

@pytest.mark.asyncio
async def test_create_user_success(handler, mock_repository):
    # Arrange
    mock_repository.find_by_email.return_value = None
    command = CreateUserCommand(name="John Doe", email="john@example.com")
    
    # Act
    user_id = await handler.handler(command)
    
    # Assert
    assert user_id is not None
    mock_repository.find_by_email.assert_called_once_with("john@example.com")
    mock_repository.create.assert_called_once()

@pytest.mark.asyncio
async def test_create_user_conflict(handler, mock_repository):
    # Arrange
    mock_repository.find_by_email.return_value = AsyncMock()  # Usuario existente
    command = CreateUserCommand(name="John Doe", email="john@example.com")
    
    # Act & Assert
    with pytest.raises(ConflictDomainException):
        await handler.handler(command)
```

### Configuración por Entorno

```python
# config/development.yaml
env:
  reload: true
  openapi: true
  firestore:
    credential_path: "dev-credentials.json"
    database: "development"

# config/production.yaml
env:
  reload: false
  openapi: false
  firestore:
    credential_path: "/secrets/firestore-credentials.json"
    database: "production"

middlewares:
  - class_: "ErrorMiddleware"
    options:
      log_stack_traces: false
```

### Deployment

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "main.py"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - CONFIG_PATH=config/production.yaml
      - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json
    volumes:
      - ./credentials.json:/app/credentials.json:ro
```

---

## Mejores Prácticas

### 1. Estructura de Proyecto

```
my-app/
├── common/                    # Framework (no tocar)
├── features/                  # Features organizados por dominio
│   ├── users/
│   │   ├── commands/         # Commands y handlers
│   │   ├── queries/          # Queries y handlers  
│   │   ├── models/           # Domain models y documents
│   │   ├── events.py         # Domain events y handlers
│   │   └── __init__.py       # API routes
│   └── orders/
├── services/                  # Servicios compartidos
│   ├── email_service.py
│   └── external_apis.py
├── config/                    # Configuraciones por entorno
│   ├── development.yaml
│   ├── staging.yaml
│   └── production.yaml
├── tests/                     # Tests organizados como src
├── credentials/               # Credenciales (no versionar)
├── requirements.txt
└── main.py
```

### 2. Convenciones de Nomenclatura

- **Commands**: `CreateUserCommand`, `UpdateOrderCommand`
- **Queries**: `GetUserQuery`, `SearchOrdersQuery`
- **Handlers**: `CreateUserHandler`, `GetUserHandler`  
- **Events**: `UserCreatedEvent`, `OrderShippedEvent`
- **Models**: `User`, `Order` (dominio) vs `UserDocument`, `OrderDocument` (infraestructura)
- **Repositories**: `UserRepository` (dominio) vs `UserFirestoreRepository` (infraestructura)

### 3. Validación y Business Rules

```python
# En Value Objects
class Email(ValueObject):
    value: str
    
    def __init__(self, value: str):
        if not self._is_valid(value):
            raise BadRequestDomainException("Invalid email format")
        super().__init__(value=value)

# En Entities
class User(BaseEntity):
    def change_email(self, new_email: Email):  # Use Value Objects
        if self.email == new_email:
            return  # No change needed
        
        self.email = new_email
        self.add_event(UserEmailChangedEvent(...))

# En Commands
class CreateUserCommand(Command):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr  # Use Pydantic types
    age: int = Field(..., ge=18, le=120)
```

### 4. Error Handling

```python
# Usar excepciones específicas del framework
if user_exists:
    raise ConflictDomainException("User already exists")

if not user:
    raise NotFoundDomainException("User not found")

if invalid_data:
    raise BadRequestDomainException("Invalid user data")

# Para APIs externas
try:
    response = await external_api.call()
except httpx.TimeoutException:
    raise HttpApiRetryException("External service timeout")
```

### 5. Performance y Monitoring

```python
# Usar pagination en queries
class SearchUsersQuery(Command):
    search_term: str
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

# Implementar cache en queries costosas
@pipelines(CachePipeline)
class GetUserStatsHandler(CommandHadler[GetUserStatsQuery]):
    pass

# Configurar métricas personalizadas
from opentelemetry import metrics

meter = metrics.get_meter(__name__)
user_creation_counter = meter.create_counter("users_created_total")

# En handler
async def handler(self, command: CreateUserCommand):
    user_id = await self.create_user(command)
    user_creation_counter.add(1, {"tenant": command.tenant_id})
    return user_id
```

---

## Troubleshooting

### Errores Comunes

1. **"Component not registered"**
   ```python
   # Asegúrate de registrar componentes
   @component
   class MyService:
       pass
   ```

2. **"Circular dependency detected"**
   ```python
   # Usar interfaces o injection tardía
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from .other_service import OtherService
   ```

3. **"Missing dependency"**
   ```python
   # Verificar que todas las dependencias estén registradas
   @inject
   def __init__(self, service: MyService = deps(MyService)):
       pass
   ```

4. **"Firestore permission denied"**
   - Verificar credenciales en `credentials.json`
   - Comprobar reglas de Firestore
   - Validar permisos de Service Account

### Debugging

```python
# Habilitar logs detallados
import logging
logging.basicConfig(level=logging.DEBUG)

# Usar Console Dialect para ver operaciones Firestore
from common.infrastructure.unit_of_work import VerboseConsoleDialect

# Verificar trazas OpenTelemetry
# Las trazas incluyen información detallada sobre cada operación
```

---

## Migración y Versionado

### Schema Migrations

```python
# migrations/001_add_user_tenant.py
from common.infrastructure import RepositoryFirestore
from features.users.models import UserDocument

async def migrate():
    repo = UserRepository()
    users = await repo.find_by_field("tenant_id", None)  # Sin tenant
    
    for user in users:
        user.tenant_id = "default"
        await repo.update(user)
```

### API Versioning

```yaml
# Para versionado de API
openapi:
  tags:
    users_v1:
      description: "Users API v1"
      prefix: "/api/v1/users"
    users_v2:
      description: "Users API v2"  
      prefix: "/api/v2/users"
```

---

## Conclusión

Este framework proporciona una base sólida para desarrollar aplicaciones FastAPI robustas siguiendo principios de arquitectura limpia y DDD. Las características clave incluyen:

- **Separación clara de responsabilidades** entre capas
- **Inyección de dependencias automática** con IoC container
- **Patrón Mediator** para desacoplar lógica de negocio
- **Integración nativa con Firestore** incluyendo subcolecciones
- **Observabilidad completa** con OpenTelemetry
- **Manejo robusto de errores** con responses estandarizadas
- **Cliente HTTP avanzado** con retry automático
- **Documentación OpenAPI mejorada** automáticamente

El framework está diseñado para escalar desde prototipos rápidos hasta aplicaciones empresariales complejas, manteniendo siempre la claridad arquitectónica y la facilidad de testing.

Para más información o soporte, consulta la documentación de cada módulo específico o contacta al equipo de desarrollo.