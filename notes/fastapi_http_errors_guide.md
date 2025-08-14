# Guía de Códigos de Error HTTP en FastAPI

> **📍 Punto clave**: La distinción entre **400**, **409** y **422** no es intuitiva si vienes de otros frameworks o APIs. Esta guía te ayudará a entender cuándo usar cada uno correctamente.

## 🔢 422 Unprocessable Entity (FastAPI por defecto)

### Cuándo lo devuelve FastAPI automáticamente

FastAPI devuelve automáticamente un código **422** cuando:

- La validación de datos de entrada (query, path, body) falla **después** de que la petición sea sintácticamente válida
- El JSON es válido y tiene el `Content-Type` correcto, pero los datos no cumplen el esquema
- **Ejemplo**: envías `{"id": "abc"}` cuando `id` debería ser un `int`

### ¿Por qué no devuelve 400 en estos casos?

FastAPI sigue la especificación OpenAPI + Pydantic y asume que si la sintaxis es correcta pero los datos no cumplen el esquema, es un **422** (error semántico), no un **400**.

### Ejemplo práctico

```python
@app.post("/items")
def create_item(item: Item):
    return item
```

Si envías un JSON con tipos incorrectos, FastAPI devuelve **422** automáticamente.

---

## 🚫 400 Bad Request

### Cuándo usarlo manualmente

Utiliza **400** cuando la petición está mal formada **a nivel de cliente**, antes de siquiera validar el modelo de datos.

### Ejemplos típicos

- Faltan parámetros obligatorios en la query
- Estructura de JSON incorrecta (mal formato, comas extra, etc.) que FastAPI no detecta como 422
- Datos coherentes pero que no cumplen una precondición básica de negocio

### Ejemplo de implementación

```python
if page < 0:
    raise HTTPException(
        status_code=400, 
        detail="El parámetro 'page' no puede ser negativo"
    )
```

---

## ⚡ 409 Conflict

### Cuándo usarlo

Utiliza **409** cuando el cliente envía datos correctos pero entran en **conflicto con el estado actual del sistema**.

### Ejemplos de uso

- Intentar crear un recurso con un identificador que ya existe
- Intentar hacer una operación que choca con otra transacción en curso
- Violación de restricciones de unicidad

### Ejemplo de implementación

```python
if username_exists(username):
    raise HTTPException(
        status_code=409, 
        detail="El nombre de usuario ya existe"
    )
```

---

## 📋 Tabla de Referencia Rápida

| Código | Cuándo usarlo en FastAPI |
|--------|-------------------------|
| **400** | Datos faltantes o inválidos detectados manualmente antes de validación, o reglas de negocio muy básicas |
| **409** | Conflicto con estado actual del recurso/sistema |
| **422** | Error de validación automática de FastAPI/Pydantic (tipos, formato, restricciones) |

---

## 💡 Consejos Adicionales

- **422** es el comportamiento por defecto de FastAPI para errores de validación
- **400** requiere que levantes la excepción manualmente
- **409** es específico para conflictos de estado, no para errores de formato
- Siempre proporciona mensajes de error descriptivos en el campo `detail`