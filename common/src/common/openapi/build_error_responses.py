from typing import Dict
from common.errors import ErrorResponse


def build_error_responses(*codes: int) -> Dict[int, dict]:
    """Genera un diccionario de responses para FastAPI
    solo aceptando 400, 404 y 409.
    """
    allowed_codes = {
        400: "Bad Request",
        404: "Not Found",
        409: "Conflict",
    }

    result = {}
    for code in codes:
        if code not in allowed_codes:
            raise ValueError(f"Código {code} no permitido. Solo 400, 404 o 409.")
        result[code] = {"description": allowed_codes[code], "model": ErrorResponse}
    return result
