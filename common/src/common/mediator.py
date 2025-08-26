from typing import TypeVar, Generic, get_args, Dict, Type, List, Callable, Any, Optional
from pydantic import BaseModel
from abc import ABC, ABCMeta, abstractmethod
from functools import wraps

class Command(BaseModel):
    pass

T = TypeVar("T", bound=Command)

# Excepción para commands duplicados
class DuplicateCommandError(Exception):
    def __init__(self, command_type: Type[Command], existing_service: Type, new_service: Type):
        super().__init__(
            f"Command {command_type.__name__} is already registered to {existing_service.__name__}. "
            f"Cannot register it to {new_service.__name__}."
        )

# Registry global
_COMMAND_TO_SERVICE_REGISTRY: Dict[Type[Command], Type] = {}
_COMMAND_TO_PIPELINES_REGISTRY: Dict[Type[Command], List[Type]] = {}

class ServiceMeta(ABCMeta):
    """Metaclass que registra automáticamente los Services al definir la clase"""
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace)
        
        if name != 'Service' and bases:
            command_type = mcs._extract_command_type(cls)
            if command_type:
                mcs._register_service(cls, command_type)
        
        return cls
    
    @staticmethod
    def _extract_command_type(cls) -> Optional[Type[Command]]:
        if hasattr(cls, '__orig_bases__'):
            for base in cls.__orig_bases__:
                args = get_args(base)
                if args:
                    for arg in args:
                        if isinstance(arg, type) and issubclass(arg, Command):
                            return arg
        return None
    
    @staticmethod
    def _register_service(service_class: Type, command_type: Type[Command]):
        global _COMMAND_TO_SERVICE_REGISTRY
        
        if command_type in _COMMAND_TO_SERVICE_REGISTRY:
            existing_service = _COMMAND_TO_SERVICE_REGISTRY[command_type]
            if existing_service != service_class:
                raise DuplicateCommandError(command_type, existing_service, service_class)
        
        _COMMAND_TO_SERVICE_REGISTRY[command_type] = service_class
        print(f"🔄 Service registered: {command_type.__name__} -> {service_class.__name__}")

class PipelineMeta(ABCMeta):
    """Metaclass que registra automáticamente los Pipelines al definir la clase"""
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        cls = super().__new__(mcs, name, bases, namespace)
        
        if name != 'Pipeline' and bases:
            command_type = mcs._extract_command_type(cls)
            if command_type:
                mcs._register_pipeline(cls, command_type)
        
        return cls
    
    @staticmethod
    def _extract_command_type(cls) -> Optional[Type[Command]]:
        if hasattr(cls, '__orig_bases__'):
            for base in cls.__orig_bases__:
                args = get_args(base)
                if args:
                    for arg in args:
                        if isinstance(arg, type) and issubclass(arg, Command):
                            return arg
        return None
    
    @staticmethod
    def _register_pipeline(pipeline_class: Type, command_type: Type[Command]):
        global _COMMAND_TO_PIPELINES_REGISTRY
        
        if command_type not in _COMMAND_TO_PIPELINES_REGISTRY:
            _COMMAND_TO_PIPELINES_REGISTRY[command_type] = []
        
        _COMMAND_TO_PIPELINES_REGISTRY[command_type].append(pipeline_class)
        print(f"🔗 Pipeline registered: {command_type.__name__} -> {pipeline_class.__name__}")

# Context para pasar datos entre pipelines
class PipelineContext:
    def __init__(self, command: Command):
        self.command = command
        self.data: Dict[str, Any] = {}
        self.cancelled = False
        
    def cancel(self):
        """Cancela la ejecución del pipeline"""
        self.cancelled = True
        
    def set_data(self, key: str, value: Any):
        """Almacena datos para pipelines posteriores"""
        self.data[key] = value
        
    def get_data(self, key: str, default: Any = None):
        """Obtiene datos almacenados por pipelines anteriores"""
        return self.data.get(key, default)

class Service(Generic[T], ABC, metaclass=ServiceMeta):    
    @abstractmethod
    def handler(self, command: T) -> Any:
        pass

class Pipeline(Generic[T], ABC, metaclass=PipelineMeta):
    """Pipeline base que se ejecuta antes/después del service"""
    
    # Orden de ejecución (menor número = se ejecuta antes)
    order: int = 100
    
    @abstractmethod
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        """
        Handler del pipeline
        - context: contexto compartido entre pipelines
        - next_handler: función para ejecutar el siguiente pipeline/service
        """
        pass

class Mediator:
    """Mediator que orquesta la ejecución de pipelines y services"""
    
    def __init__(self):
        pass
    
    def send(self, command: Command) -> Any:
        """Envía un command y ejecuta todos los pipelines + service"""
        command_type = type(command)
        
        # Obtener service
        if command_type not in _COMMAND_TO_SERVICE_REGISTRY:
            raise ValueError(f"No service registered for command {command_type.__name__}")
        
        service_class = _COMMAND_TO_SERVICE_REGISTRY[command_type]
        service = service_class()
        
        # Obtener pipelines y ordenarlos
        pipeline_classes = _COMMAND_TO_PIPELINES_REGISTRY.get(command_type, [])
        pipelines = [pipeline_class() for pipeline_class in pipeline_classes]
        pipelines.sort(key=lambda p: p.order)
        
        # Crear contexto
        context = PipelineContext(command)
        
        print(f"🚀 Executing command {command_type.__name__}")
        print(f"   Pipelines: {[p.__class__.__name__ for p in pipelines]}")
        
        # Crear cadena de ejecución
        def create_chain():
            # El último handler es el service
            def service_handler():
                if context.cancelled:
                    print("   ❌ Execution cancelled by pipeline")
                    return None
                print(f"   ⚡ Executing service: {service_class.__name__}")
                return service.handler(command)
            
            # Crear la cadena desde el final hacia el principio
            next_handler = service_handler
            
            for pipeline in reversed(pipelines):
                def create_pipeline_handler(pipe, next_h):
                    def pipeline_handler():
                        if context.cancelled:
                            return None
                        print(f"   🔗 Executing pipeline: {pipe.__class__.__name__}")
                        return pipe.handler(context, next_h)
                    return pipeline_handler
                
                next_handler = create_pipeline_handler(pipeline, next_handler)
            
            return next_handler
        
        # Ejecutar la cadena
        chain = create_chain()
        result = chain()
        
        print(f"   ✅ Command {command_type.__name__} completed")
        return result

# ==================== EJEMPLOS DE USO ====================

# Commands
class LoginCommand(Command):
    username: str
    password: str

class CreateUserCommand(Command):
    username: str
    email: str
    
class LogoutCommand(Command):
    user_id: int

# Services
print("=== REGISTERING SERVICES ===")

class LoginService(Service[LoginCommand]):
    def handler(self, command: LoginCommand) -> dict:
        return {"status": "logged_in", "user": command.username}

class CreateUserService(Service[CreateUserCommand]):
    def handler(self, command: CreateUserCommand) -> dict:
        return {"status": "user_created", "user": command.username, "email": command.email}

class LogoutService(Service[LogoutCommand]):
    def handler(self, command: LogoutCommand) -> dict:
        return {"status": "logged_out", "user_id": command.user_id}

# Pipelines
print("\n=== REGISTERING PIPELINES ===")

class AuthenticationPipeline(Pipeline[LoginCommand]):
    order = 10  # Se ejecuta primero
    
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        command = context.command
        print(f"     🔐 Authenticating user: {command.username}")        
        # Simular validación
        if command.password == "wrong":
            context.set_data("auth_error", "Invalid credentials")
            context.cancel()
            return {"error": "Authentication failed"}
        
        context.set_data("auth_time", "2025-08-25 10:30:00")
        return next_handler()

class LoggingPipeline(Pipeline[LoginCommand]):
    order = 20  # Se ejecuta después de auth
    
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        command = context.command
        print(f"     📝 Logging attempt for user: {command.username}")
        
        result = next_handler()
        
        # Log después de la ejecución
        if result and "error" not in result:
            print(f"     📝 Login successful for: {command.username}")
        
        return result

class ValidationPipeline(Pipeline[CreateUserCommand]):
    order = 5  # Se ejecuta muy temprano
    
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        command = context.command
        print(f"     ✅ Validating user data: {command.username}")
        
        if "@" not in command.email:
            context.cancel()
            return {"error": "Invalid email format"}
        
        if len(command.username) < 3:
            context.cancel()
            return {"error": "Username too short"}
        
        return next_handler()

class NotificationPipeline(Pipeline[CreateUserCommand]):
    order = 100  # Se ejecuta después del service
    
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        result = next_handler()
        
        # Notificar después de crear usuario
        if result and "error" not in result:
            command = context.command
            print(f"     📧 Sending welcome email to: {command.email}")
        
        return result

class AuditPipeline(Pipeline[LogoutCommand]):
    order = 1  # Se ejecuta muy temprano
    
    def handler(self, context: PipelineContext, next_handler: Callable[[], Any]) -> Any:
        command = context.command
        print(f"     📊 Auditing logout for user_id: {command.user_id}")
        
        result = next_handler()
        
        print(f"     📊 Logout audit complete for user_id: {command.user_id}")
        return result

# Demo
if __name__ == "__main__":
    mediator = Mediator()
    
    print("\n" + "="*50)
    print("DEMO: MEDIATOR WITH PIPELINES")
    print("="*50)
    
    # Login exitoso
    print("\n🟢 LOGIN SUCCESS SCENARIO:")
    login_cmd = LoginCommand(username="alice", password="secret123")
    result = mediator.send(login_cmd)
    print(f"Result: {result}")
    
    # Login fallido
    print("\n🔴 LOGIN FAILURE SCENARIO:")
    login_cmd_fail = LoginCommand(username="bob", password="wrong")
    result = mediator.send(login_cmd_fail)
    print(f"Result: {result}")
    
    # Create user exitoso
    print("\n🟢 CREATE USER SUCCESS SCENARIO:")
    create_cmd = CreateUserCommand(username="charlie", email="charlie@example.com")
    result = mediator.send(create_cmd)
    print(f"Result: {result}")
    
    # Create user con validación fallida
    print("\n🔴 CREATE USER VALIDATION FAILURE:")
    create_cmd_fail = CreateUserCommand(username="x", email="invalid-email")
    result = mediator.send(create_cmd_fail)
    print(f"Result: {result}")
    
    # Logout
    print("\n🟢 LOGOUT SCENARIO:")
    logout_cmd = LogoutCommand(user_id=123)
    result = mediator.send(logout_cmd)
    print(f"Result: {result}")