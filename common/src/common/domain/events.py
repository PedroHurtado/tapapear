from abc import ABC, abstractmethod
from datetime import datetime
from typing import  Dict, List, Type
from uuid import uuid4
import asyncio
from functools import wraps
from pydantic import BaseModel


# ================================
# EVENTOS BASE Y ENUM
# ================================

class FrozenMeta(type):
    def __setattr__(cls, key, value):
        if key in cls.__dict__:
            raise AttributeError(f"Cannot reassign class attribute '{key}'")
        super().__setattr__(key, value)

class EnumEvent(metaclass=FrozenMeta):
    """
    Clase base para enumeraciones constantes inmutables.
    Previene la reasignación de atributos de clase definidos.
    """
    pass






# Union type para aceptar cualquier tipo de evento


class DomainEvent(BaseModel):
    """Clase base para todos los eventos de dominio"""
    id: str = str(uuid4())
    timestamp: datetime = datetime.now()
    processed: bool = False
    event_type: str
    
    


# ================================
# PUB/SUB SYSTEM
# ================================

class EventSubscriber(ABC):
    """Interfaz base para suscriptores de eventos"""
    
    @abstractmethod
    async def handle(self, event: DomainEvent) -> None:
        """Maneja el evento recibido"""
        pass


class _EventPublisher:
    """Publisher del sistema pub/sub para eventos de dominio"""
    
    def __init__(self):        
        self._subscribers: Dict[str, List[EventSubscriber]] = {}
    
    def subscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Suscribe un handler a un tipo de evento específico"""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        
        if subscriber not in self._subscribers[event_type]:
            self._subscribers[event_type].append(subscriber)
    
    def unsubscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Desuscribe un handler de un tipo de evento"""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(subscriber)
                if not self._subscribers[event_type]:
                    del self._subscribers[event_type]
            except ValueError:
                pass  # El subscriber no estaba suscrito
    
    async def publish(self, event: DomainEvent) -> None:
        """Publica un evento a todos los suscriptores registrados"""
        if event.event_type in self._subscribers:
            # Ejecutar todos los handlers de forma concurrente
            tasks = [
                subscriber.handle(event) 
                for subscriber in self._subscribers[event.event_type]
            ]
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_subscribers(self, event_type: str) -> List[EventSubscriber]:
        """Obtiene la lista de suscriptores para un tipo de evento"""
        return self._subscribers.get(event_type, []).copy()
    
    def get_all_subscribers(self) -> Dict[str, List[EventSubscriber]]:
        """Obtiene todos los suscriptores registrados"""
        return {
            event_type: subscribers.copy() 
            for event_type, subscribers in self._subscribers.items()
        }


# Instancia global del publisher (Singleton)
event_publisher = _EventPublisher()


# ================================
# DECORADOR PARA EVENT HANDLERS
# ================================

def event_handler(*event_types: str,**dependencies):
    """
    Decorador para registrar automáticamente event handlers
    
    Usage:
        @event_handler(UserEventType.USER_CREATED, UserEventType.USER_UPDATED)
        class UserNotificationHandler(EventSubscriber):
            async def handle(self, event: DomainEvent) -> None:
                # Lógica del handler
                pass
    """
    def decorator(cls: Type[EventSubscriber]) -> Type[EventSubscriber]:
        # Verificar que la clase implemente EventSubscriber
        if not issubclass(cls, EventSubscriber):
            raise TypeError(f"La clase {cls.__name__} debe heredar de EventSubscriber")
        
        # Crear instancia automáticamente y registrarla
        handler_instance = cls(**dependencies)
        
        # Registrar la instancia para los tipos de eventos especificados
        for event_type in event_types:
            event_publisher.subscribe(event_type, handler_instance)
        
        # Agregar metadatos para debugging
        cls._registered_events = event_types
        cls._handler_instance = handler_instance
        
        return cls
    
    return decorator


# ================================
# CLASE BASE PARA ENTIDADES CON EVENTOS
# ================================

class DomainEventContainer:
    """Clase base que mantiene una lista de eventos de dominio"""
    
    def __init__(self):
        self._domain_events: List[DomainEvent] = []
    
    def add_event(self, event: DomainEvent) -> None:
        """Agrega un evento de dominio a la lista"""
        if not isinstance(event, DomainEvent):
            raise TypeError("El evento debe ser una instancia de DomainEvent")
        self._domain_events.append(event)
    
    def remove_event(self, event: DomainEvent) -> bool:
        """
        Remueve un evento específico de la lista
        Returns: True si se removió, False si no se encontró
        """
        try:
            self._domain_events.remove(event)
            return True
        except ValueError:
            return False
    
    def get_events(self) -> List[DomainEvent]:
        """Obtiene una copia de la lista de eventos"""
        return self._domain_events.copy()
    
    def clear_events(self) -> List[DomainEvent]:
        """
        Limpia la lista de eventos y retorna los eventos que tenía
        Útil para obtener y limpiar eventos después de procesarlos
        """
        events = self._domain_events.copy()
        self._domain_events.clear()
        return events
    
    def has_events(self) -> bool:
        """Verifica si hay eventos pendientes"""
        return len(self._domain_events) > 0
    
    def event_count(self) -> int:
        """Retorna el número de eventos pendientes"""
        return len(self._domain_events)
    
__all__ = [
    'EnumEvent',
    'EventSubscriber',
    'event_handler',
    'DomainEvent',
    'DomainEventContainer',
    'event_publisher',
]