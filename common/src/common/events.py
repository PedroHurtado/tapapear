import asyncio
from common.domain.events import(    
    EnumEvent,
    DomainEvent,
    DomainEventContainer,
    event_handler,
    event_publisher,
    EventSubscriber
)
# ================================
# EJEMPLOS DE USO
# ================================
class UserEvent(EnumEvent):
    CREATED="created"
class UserCreateEvent(DomainEvent):
    user_id:str
    user_name:str 
    email:str
    event_type:str = UserEvent.CREATED

# Ejemplo de entidad de dominio que usa eventos
class User(DomainEventContainer):
    def __init__(self, user_id: str, user_name: str, email: str):
        super().__init__()
        self.user_id = user_id
        self.username = user_name
        self.email = email
        
        # Agregar evento de creación
        self.add_event(UserCreateEvent(
            user_id=user_id,
            user_name=user_name,
            email=email
        ))





@event_handler(UserEvent.CREATED, a=1)
class UserAnalyticsHandler(EventSubscriber):
    def __init__(self,a:int):
        print(a)
        super().__init__()
    async def handle(self, event: UserCreateEvent) -> None:        
            print(f"📊 Registrando nuevo usuario en analytics: {event.user_name}")
            await asyncio.sleep(0.1)  # Simular trabajo asíncrono




# ================================
# EJEMPLO DE USO COMPLETO
# ================================

async def example_usage():
    """Ejemplo de cómo usar el sistema de eventos"""
    
    print("=== Sistema de Eventos de Dominio - Ejemplo ===\n")
    
    # 1. Crear una entidad que genera eventos
    user = User("user-123", "juan_perez", "juan@email.com")
    
    print(f"Usuario creado. Eventos pendientes: {user.event_count()}")
    
    # 2. Obtener y procesar eventos
    pending_events = user.clear_events()
    
    print(f"Procesando {len(pending_events)} eventos...\n")
    
    # 3. Publicar eventos (esto activará todos los handlers registrados)
    for event in pending_events:
        print(f"Publicando evento: {event.event_type}")
        await event_publisher.publish(event)
        print(f"Evento publicado - ID: {event.id}\n")
    
    

    

    

# Para ejecutar el ejemplo:
if __name__ == "__main__":
    asyncio.run(example_usage())