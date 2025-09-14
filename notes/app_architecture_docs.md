# Documentación de Arquitectura de la Aplicación

## Config
Carga el archivo `config.yaml` y crea las clases necesarias para la configuración de la aplicación.

## Context
Instancia global utilizada para configurar la aplicación en el momento de la carga.

## Domain
Clases base para el dominio de la aplicación:

- **BaseEntity**: Garantiza que una entidad sea igual a otra si sus identificadores son iguales
- **DomainEvent**: Clases para publicar eventos de dominio
- **DomainEventContainer**: Mixing para agregar control de eventos al dominio
- **ValueObject**: Clase que será igual a otra si todos sus atributos son iguales

## Error
- **ErrorResponse**: Respuesta de error de la API

## Exception
Excepciones específicas del dominio:

- **ConflictDomainException**: No se puede repetir DNI
- **BadRequestDomainException**: Email mal formado
- **NotFoundDomainException**: No se encuentra usuario

## Http Client
Cliente HTTP para realizar peticiones externas.

## Inflect
Define una función para pluralizar elementos.

## Infraestructura

### Document
Clase base de la que heredarán todos los documentos que se van a guardar en base de datos.

### Embeddable
Correspondencia al ValueObject del dominio para guardar los datos.

### Repository
Operaciones básicas: `add`, `get`, `update` y `remove`

### Repository FireStore
Responsable de guardar datos en la base de datos Firestore.

## Módulo IOC (Inversión de Control)

### Component
Decorador para registrar objetos en el contenedor de dependencias.

### Tipos de Registro

- **ProviderType**: Permite valores de tipo singleton
- **Factory**: Se crea una instancia cada vez que se invoca
- **Resource**: No se utiliza, sirve para objetos de enter/exit
- **Object**: Sirve para meter objetos no instanciados
- **List**: Una lista de cualquiera de los otros tipos

### Container
Contenedor de dependencias.

### Inject
Decorador para indicar al contenedor de dependencias que comience a inyectar dependencias.

### Deps
Función que indica al contenedor de dependencias qué objeto necesita.

## Mapper

### MapperClass
Función que mapea de una clase a otra.

### TypeMapper
Útil para la inyección de dependencias.

## Mediator
Su método `send` envía un comando desde el controlador al use case y ejecuta una cadena de pipelines.

## EventBus
Notifica los eventos del dominio a los event handlers.

## Decoradores

### Pipelines
Para elegir los pipelines a ejecutar en el command handler y en el event handler.

### IgnorePipeline
Ignora los pipelines.

## Pipelines

### LoggerPipeline
Sirve para hacer logging de los comandos de entrada y salida.

### TransactionPipeline
Sirve para garantizar la transaccionalidad en base de datos. Se ignora siempre en los métodos de lectura.

## Middleware

### AuthMiddleware
Se encarga de validar la autorización del usuario.

### CorsMiddleware
Sirve para hacer llamadas de orígenes cruzados.

## OpenAPI

### BuildErrorResponse
Permite crear una serie de respuestas para OpenAPI.

### FeatureModel
Clase base de la que heredarán todas las respuestas de la API.

## Security

### Principal
Clase que representa el usuario que ha hecho login.

### AllowAnonymous
Decorador que permite que un método sea público aun teniendo middleware de autorización.

### Authorize
Decorador que sirve para autorizar a un rol o una lista de roles.

## Server

### Entry
Función que genera respuestas sin body y con status 204.

### BuildRouter
Función para crear rutas, se le pasa un tag del `config.yaml`.

```python
router = build_router("")
```

## Telemetry
**Pendiente de desarrollar.**

## Util

### get_id
Devuelve un identificador único universal utilizado para los identificadores de las clases.

### get_now
Devuelve la fecha actual en UTC.