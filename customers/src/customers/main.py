import os
from common.server import get_routers

from fastapi import FastAPI,Depends
app = FastAPI()
#app.include_router()

routers = get_routers()
print(routers)


from functools import wraps

# Decorador que valida los tipos de los argumentos.
def validate_types(cls):
    @wraps(cls)
    def wrapper(*args, **kwargs):
        # Obtiene las anotaciones de tipo del método __init__.
        # Si no hay __init__, las anotaciones son vacías.
        annotations = cls.__init__.__annotations__ if '__init__' in cls.__dict__ else {}
        
        # `__init__` siempre tiene a `self` como el primer argumento,
        # por lo que lo ignoramos al comparar con los `args` que se pasan.
        
        # Recorre los argumentos que se pasaron a la clase.
        for name, value in zip(list(annotations.keys()), args[1:]):
            expected_type = annotations.get(name)
            
            # Si el tipo esperado no es 'return' (que es para el valor de retorno)
            # y el tipo del valor no coincide con el tipo esperado, lanza un error.
            if expected_type and name != 'return' and not isinstance(value, expected_type):
                raise TypeError(f"El argumento '{name}' debería ser de tipo '{expected_type.__name__}', "
                                f"pero se recibió '{type(value).__name__}'")
        
        # Si la validación pasa, crea la instancia de la clase.
        return cls(*args, **kwargs)

    return wrapper

# Aplica el decorador a la clase.
@validate_types
class Foo:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

# Esto funcionará sin problemas.
foo_instance = Foo(name="John", age=30)
print(f"Instancia creada con éxito: {foo_instance.name}, {foo_instance.age}")

# Esto lanzará un TypeError porque 'age' no es un entero.
try:
    Foo(name="Jane", age="veinte")
except TypeError as e:
    print(f"\nError capturado: {e}")










