from typing import List, Dict, Any, Optional, Type, get_type_hints, get_origin, get_args
from uuid import UUID
from enum import Enum
import inspect

from common.infrastructure import Document,collection


class CompiledCommand:
    """
    Comando compilado del schema de una entidad.
    No contiene operación - solo la estructura y paths.
    """
    
    def __init__(self, entity_path: str, data_fields: Dict[str, str], level: int):
        self.entity_path = entity_path  # Path con placeholders: "users/{user_id}"
        self.data_fields = data_fields  # Campos escalares: {"name": "{name}", "email": "{email}"}
        self.level = level              # Nivel de dependencia: 0=root, 1+=dependencies
    
    def __repr__(self):
        return f"CompiledCommand(path={self.entity_path}, level={self.level}, fields={list(self.data_fields.keys())})"


class SchemaCommandCompiler:
    """
    Algoritmo que compila el esquema de una clase Document en comandos abstractos
    basándose en la definición de la clase y sus campos con metadata.
    """
    
    def __init__(self):
        self.commands: List[CompiledCommand] = []
        self._processed_paths = set()
    
    def compile_schema(self, entity_class: Type[Document]) -> List[CompiledCommand]:
        """
        Compila el esquema de una clase entidad en comandos compilados.
        
        Args:
            entity_class: La clase Document (ej: User, Order, Item)
            
        Returns:
            Lista de CompiledCommand ordenados por nivel de dependencia
        """
        self.commands = []
        self._processed_paths = set()
        
        # Compilar la entidad raíz y sus dependencias
        self._compile_entity_schema(entity_class, "", 0)
        
        # Ordenar comandos por nivel (dependencias primero)
        sorted_commands = sorted(self.commands, key=lambda cmd: cmd.level)
        
        return sorted_commands
    
    def _compile_entity_schema(self, entity_class: Type[Document], base_path: str, level: int) -> None:
        """
        Compila el esquema de una entidad y sus subentidades recursivamente.
        
        Args:
            entity_class: Clase de la entidad
            base_path: Path base para la entidad
            level: Nivel de anidamiento
        """
        
        # Generar path de la entidad
        entity_path = self._build_entity_path(entity_class, base_path, level)
        
        # Evitar duplicados
        if entity_path in self._processed_paths:
            return
        self._processed_paths.add(entity_path)
        
        # Crear comando compilado para esta entidad
        command_data = self._extract_scalar_fields(entity_class)
        
        compiled_command = CompiledCommand(
            entity_path=entity_path,
            data_fields=command_data,  # Campos escalares como template
            level=level
        )
        
        self.commands.append(compiled_command)
        
        # Procesar subcolecciones recursivamente
        self._process_subcollections(entity_class, entity_path, level)
    
    def _build_entity_path(self, entity_class: Type[Document], base_path: str, level: int) -> str:
        """
        Construye el path de una entidad basándose en su clase y nivel.
        """
        from common.inflect import plural
        
        collection_name = plural(entity_class.__name__.lower())
        
        if level == 0:
            # Entidad raíz
            return f"{collection_name}/{{{entity_class.__name__.lower()}_id}}"
        else:
            # Subentidad
            return f"{base_path}/{collection_name}/{{{entity_class.__name__.lower()}_id}}"
    
    def _extract_scalar_fields(self, entity_class: Type[Document]) -> Dict[str, str]:
        """
        Extrae los campos escalares de una entidad como template.
        
        Returns:
            Dict con nombres de campos y placeholders para los valores
        """
        scalar_fields = {}
        
        # Obtener campos del modelo
        model_fields = getattr(entity_class, 'model_fields', {})
        
        for field_name, field_info in model_fields.items():
            if field_name == 'id':
                continue  # ID va en el path
            
            # Verificar si es un campo scalar (no collection ni reference)
            metadata = self._get_field_metadata(field_info)
            
            if not metadata.get('_is_subcollection') and not metadata.get('reference'):
                # Campo escalar - agregar como placeholder
                scalar_fields[field_name] = f"{{{field_name}}}"
        
        return scalar_fields
    
    def _process_subcollections(self, entity_class: Type[Document], entity_path: str, level: int) -> None:
        """
        Procesa las subcolecciones de una entidad recursivamente.
        """
        model_fields = getattr(entity_class, 'model_fields', {})
        
        for field_name, field_info in model_fields.items():
            metadata = self._get_field_metadata(field_info)
            
            # Verificar si es una subcolección
            if metadata.get('_is_subcollection'):
                # Obtener el tipo de la subentidad
                sub_entity_type = self._extract_list_type(field_info)
                
                if sub_entity_type and issubclass(sub_entity_type, Document):
                    # Procesar recursivamente la subentidad
                    self._compile_entity_schema(sub_entity_type, entity_path, level + 1)
    
    def _extract_list_type(self, field_info) -> Optional[Type]:
        """
        Extrae el tipo de elementos de una lista (ej: List[Item] -> Item).
        """
        # Obtener el annotation del campo
        annotation = getattr(field_info, 'annotation', None)
        if not annotation:
            return None
        
        # Verificar si es List[SomeType]
        origin = get_origin(annotation)
        if origin is list:
            args = get_args(annotation)
            if args:
                return args[0]
        
        return None
    
    def _get_field_metadata(self, field_info) -> Dict[str, Any]:
        """
        Extrae metadata de un field de Pydantic.
        """
        if hasattr(field_info, 'json_schema_extra') and field_info.json_schema_extra:
            return field_info.json_schema_extra.get('metadata', {})
        
        # Buscar en default si es un Field()
        default = getattr(field_info, 'default', None)
        if hasattr(default, 'json_schema_extra') and default.json_schema_extra:
            return default.json_schema_extra.get('metadata', {})
        
        return {}
    
    def print_schema_compilation(self, entity_class: Type[Document], commands: List[CompiledCommand]) -> None:
        """
        Visualiza el resultado de la compilación del schema.
        """
        print(f"=== SCHEMA COMPILATION: {entity_class.__name__} ===")
        print(f"Total comandos generados: {len(commands)}")
        print()
        
        # Agrupar por nivel
        commands_by_level = {}
        for cmd in commands:
            if cmd.level not in commands_by_level:
                commands_by_level[cmd.level] = []
            commands_by_level[cmd.level].append(cmd)
        
        # Mostrar por nivel
        for level in sorted(commands_by_level.keys()):
            level_commands = commands_by_level[level]
            print(f"📋 NIVEL {level} ({len(level_commands)} comandos):")
            
            for cmd in level_commands:
                print(f"  TEMPLATE: {cmd.entity_path}")
                
                if cmd.data_fields:
                    print(f"    └─ Campos: {list(cmd.data_fields.keys())}")
            print()


# ==================== ENTITY REGISTRY ====================

class EntityRegistry:
    """
    Registry que mantiene la cache de comandos pre-compilados para cada entidad.
    """
    
    def __init__(self):
        self._entity_schemas: Dict[Type[Document], List[CompiledCommand]] = {}
        self._compiler = SchemaCommandCompiler()
    
    def register_entity(self, entity_class: Type[Document]) -> None:
        """
        Registra una entidad y compila su schema.
        """
        if entity_class not in self._entity_schemas:
            commands = self._compiler.compile_schema(entity_class)
            self._entity_schemas[entity_class] = commands
            print(f"✅ Registered entity: {entity_class.__name__} ({len(commands)} commands)")
    
    def get_entity_commands(self, entity_class: Type[Document]) -> List[CompiledCommand]:
        """
        Obtiene los comandos compilados para una entidad.
        """
        if entity_class not in self._entity_schemas:
            raise ValueError(f"Entity {entity_class.__name__} not registered")
        
        return self._entity_schemas[entity_class].copy()
    
    def is_registered(self, entity_class: Type[Document]) -> bool:
        """
        Verifica si una entidad está registrada.
        """
        return entity_class in self._entity_schemas
    
    def list_registered_entities(self) -> List[Type[Document]]:
        """
        Lista todas las entidades registradas.
        """
        return list(self._entity_schemas.keys())


# ==================== DECORADOR @entity ====================

# Registry global (singleton)
_global_registry = EntityRegistry()

def get_entity_registry() -> EntityRegistry:
    """
    Obtiene el registry global de entidades.
    """
    return _global_registry

def entity(cls: Type[Document]) -> Type[Document]:
    """
    Decorador para registrar automáticamente una entidad en el registry.
    
    Usage:
        @entity
        class User(Document):
            name: str
            orders: List[Order] = collection()
    """
    _global_registry.register_entity(cls)
    return cls




# ==================== EJEMPLOS DE USO ====================

class Item(Document):
    
    name: str
    price: float
    quantity: int


class Order(Document):
    
    total: float
    status: str
    items: List[Item] = collection()

@entity
class User(Document):
    
    name: str
    email: str
    age: int
    orders: List[Order] = collection()

if __name__ == "__main__":
    # Importar las entidades
    
    
    def test_schema_compilation():
        """Test de compilación de schema"""
        print("=== TEST: Schema Compilation ===")
        
        compiler = SchemaCommandCompiler()
        
        # Compilar schema de User
        commands = compiler.compile_schema(User)
        compiler.print_schema_compilation(User, commands)
    
    def test_entity_decorator():
        """Test del decorador @entity"""
        print("\n=== TEST: Entity Decorator ===")
        
        # Registrar entidades usando el decorador (simulado)
        @entity
        class TestUser(Document):
            name: str
            email: str
            age: int
        
        @entity  
        class TestItem(Document):
            name: str
            price: float
        
        # Obtener registry
        registry = get_entity_registry()
        
        print(f"Entidades registradas: {[cls.__name__ for cls in registry.list_registered_entities()]}")
        
        # Obtener comandos para User
        user_commands = registry.get_entity_commands(TestUser)
        print(f"Comandos para TestUser: {len(user_commands)}")
        
        for cmd in user_commands:
            print(f"  Template: {cmd.entity_path}")          
    
    def test_runtime_usage():
        """Test de cómo se usaría en runtime"""
        print("\n=== TEST: Runtime Usage Simulation ===")
        
        registry = get_entity_registry()
        
        # En runtime, obtener comandos compilados
        user_commands = registry.get_entity_commands(User)
        
        print("📝 Simulando conversión a AbstractCommand en runtime:")
        
        for cmd in user_commands:
            print(f"  📋 CompiledCommand: {cmd.entity_path} (level {cmd.level})")
            print(f"     Campos disponibles: {list(cmd.data_fields.keys())}")
            
            # En runtime, el ChangeTracker convertiría esto a AbstractCommand:
            print(f"     → Se convierte en CREATE/UPDATE/DELETE según la operación")
            print(f"     → Path real: {cmd.entity_path.replace('{user_id}', 'user_123')}")
            print()
        
        print("💡 Los CompiledCommand son templates sin operación")
        print("💡 El ChangeTracker los convierte a AbstractCommand con operación real")
    
    # Ejecutar tests
    #test_schema_compilation()
    test_entity_decorator()  
    #test_runtime_usage()
    
    print("\n🚀 Schema Command Compiler implementado correctamente")
    print("Uso: @entity decorator + EntityRegistry para cache de comandos")