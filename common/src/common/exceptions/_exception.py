
class ApplicationException(Exception):
     def __init__(self, message: str) -> None:
          super.__init__(message)

class DomainException(ApplicationException):
    """
        De esta clase heredan:

            ConflictDomainException->409

            BadRequestDomainException->400

            NotFoundDomainException->404

    """

class ConflictDomainException(DomainException):
    """representa en la respuesta un 409"""

class BadRequestDomainException(DomainException):
    """representa en la respuesta un 400"""

class NotFoundDomainException(DomainException):
    """representa en la respuesta un 404"""

class HttpApiException(ApplicationException):
    """
        clase base para todas las exceptions HttpApiException

        HttpApiRetryException      

        HTTPApiStatusError

    """

class HttpApiRetryException(HttpApiException):
    """
            clase para todos los reintentos de  HttpApiException
            puede tener un status code asociado
    """

class HTTPApiStatusError(HttpApiException):
    """
        clase que representa el status code devuelto por 
        httpx y que tiene un status code asociado
    """


