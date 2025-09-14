from typing import  Optional
from ._constants import INTERNALSERVERERROR,NOTFOUND,CONFLICT,BADREQUEST,SERVICEUNAVAILABLE

# ----------------- Literales de estado HTTP -----------------





# ----------------- Excepciones Base -----------------

class ApplicationException(Exception):
    """
    Excepción base de la aplicación.
    Contiene los campos necesarios para mapear a ErrorResponse.
    """
    def __init__(
        self,
        message: str,
        status: int = INTERNALSERVERERROR,  # por defecto 500
        error: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.error = error or self.__class__.__name__
        self.cause = cause
        self.exception = type(self).__name__
        self.path: Optional[str] = None  # se rellena en el handler
    


# ----------------- Domain Exceptions -----------------

class DomainException(ApplicationException):
    """Excepciones de dominio (lógica de negocio)."""


class ConflictDomainException(DomainException):
    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, status=CONFLICT, error="Conflict", cause=cause)


class BadRequestDomainException(DomainException):
    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, status=BADREQUEST, error="Bad Request", cause=cause)


class NotFoundDomainException(DomainException):
    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, status=NOTFOUND, error="Not Found", cause=cause)


# ----------------- HTTP API Exceptions -----------------

class HttpApiException(ApplicationException):
    """Errores en llamadas a APIs externas."""


class HttpApiRetryException(HttpApiException):
    def __init__(self, message: str, cause: Optional[BaseException] = None):
        super().__init__(message, status=SERVICEUNAVAILABLE, error="Service Unavailable", cause=cause)


class HttpApiStatusError(HttpApiException):
    def __init__(self, message: str, status: int, cause: Optional[BaseException] = None):
        super().__init__(message, status=status, error="Upstream API Error", cause=cause)


# ----------------- Database Exceptions -----------------

class DataBaseException(ApplicationException):
    def __init__(self, message: str, status: int = INTERNALSERVERERROR, cause: Optional[BaseException] = None):
        super().__init__(message, status=status, error="Database Error", cause=cause)


