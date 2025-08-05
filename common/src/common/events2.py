from pydantic import BaseModel
from typing import Callable

# Ya no usamos Enum, solo constantes tipo str
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

class OrderEventType(EnumEvent):
    UNO = "order:uno"
    ADIOS = "order:adios"

# ✅ Uso
print(OrderEventType.UNO)        # 'order:uno'
OrderEventType.NUEVO = "extra"   # ✅ se permite crear nuevos (opcional)
#OrderEventType.UNO = "modificado" # ❌ AttributeError



# Clase base del evento
class Event(BaseModel):
    event_type: str

# Ejemplo de evento concreto
class EventConcreto(Event):
    event_type: str = OrderEventType.UNO

event = EventConcreto()
print(event)
    


