from datetime import datetime, timezone
from typing import List, Any, Dict, Optional
from common.util import get_id, get_now
from pydantic import(
     BaseModel, model_serializer, model_validator, SerializerFunctionWrapHandler, Field, ConfigDict
)

from uuid import UUID


class DomainEvent(BaseModel):
    """Clase base para todos los eventos de dominio"""

    model_config = ConfigDict(frozen=True, extra='forbid')
    

    id: UUID = Field(default_factory=lambda: get_id())
    timestamp: datetime = Field(default_factory=lambda: get_now())
    processed: bool = False
    event_type: str = ""
    aggregate:str
    aggregate_id:UUID
    data: Optional[BaseModel | Dict] = None
    
    @model_validator(mode='before')
    @classmethod  
    def __set_event_type(cls, values):
        if isinstance(values, dict):
            values['event_type'] = cls.__name__
        return values
    
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
        return {k: v for k, v in data.items() if v is not None}


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
        Remueve un evento específico de la lista si se encuentra       
        """
        if event in self._domain_events:
            self._domain_events.remove(event)

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
    "DomainEvent",
    "DomainEventContainer",
]
