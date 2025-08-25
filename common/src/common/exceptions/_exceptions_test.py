import traceback 
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


def utc_now_ms() -> str:
    """Devuelve la fecha/hora actual en UTC con milisegundos (ISO 8601)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ApplicationException(Exception):
    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.cause = cause
        self.timestamp = utc_now_ms()
        # Capturar el stacktrace en el momento de creación de la excepción
        self._stacktrace = traceback.format_stack()[:-1]  # Excluir la línea actual
        
    def get_stacktrace(self) -> str:
        """Devuelve el stacktrace formateado de esta excepción"""
        return ''.join(self._stacktrace)
    
    def get_cause_chain(self) -> List['ApplicationException']:
        """Devuelve la cadena completa de causas"""
        chain = []
        current = self.cause
        while current is not None:
            chain.append(current)
            if hasattr(current, 'cause'):
                current = current.cause
            else:
                current = None
        return chain
    
    def get_full_stacktrace_info(self) -> Dict[str, Any]:
        """
        Devuelve información completa del stacktrace incluyendo causas anidadas
        """
        info = {
            'level': 0,  # excepción principal siempre Level 0
            'exception_type': self.__class__.__name__,
            'message': str(self),
            'timestamp': self.timestamp,
            'stacktrace': self.get_stacktrace(),
            'causes': []
        }
        
        # Procesar causas anidadas
        cause_chain = self.get_cause_chain()
        for i, cause in enumerate(cause_chain):
            cause_info = {
                'level': i + 1,
                'exception_type': cause.__class__.__name__,
                'message': str(cause),
            }
            
            # Si la causa también es ApplicationException, obtener su stacktrace
            if isinstance(cause, ApplicationException):
                cause_info['stacktrace'] = cause.get_stacktrace()
                cause_info['timestamp'] = cause.timestamp
            else:
                # Para excepciones estándar de Python, intentar obtener el traceback
                cause_info['stacktrace'] = ''.join(traceback.format_exception(
                    type(cause), cause, cause.__traceback__
                )) if cause.__traceback__ else 'No stacktrace available'
            
            info['causes'].append(cause_info)
        
        return info
    
    def log_exception(self, logger: logging.Logger, level: int = logging.ERROR) -> None:
        """
        Registra la excepción y todas sus causas en el logger especificado
        """
        info = self.get_full_stacktrace_info()
        
        # Log de la excepción principal con Level 0
        logger.log(level, f"[{info['exception_type']}]")
        logger.log(level, f"Level: {info['level']}")
        logger.log(level, f"Message: {info['message']}")
        logger.log(level, f"Timestamp: {info['timestamp']}")
        logger.log(level, f"Stacktrace:\n{info['stacktrace']}")
        
        # Log de las causas
        for cause in info['causes']:
            logger.log(level, f"--- Caused by [{cause['exception_type']}] ---")
            logger.log(level, f"Level: {cause['level']}")
            logger.log(level, f"Message: {cause['message']}")
            if 'timestamp' in cause:
                logger.log(level, f"Timestamp: {cause['timestamp']}")
            logger.log(level, f"Stacktrace:\n{cause['stacktrace']}")


class DomainException(ApplicationException):
    """De esta clase heredan ConflictDomainException->409, BadRequestDomainException->400, NotFoundDomainException->404"""
    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message, cause)


class ConflictDomainException(DomainException):
    """representa en la respuesta un 409"""
    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message, cause)


class BadRequestDomainException(DomainException):
    """representa en la respuesta un 400"""
    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message, cause)


class NotFoundDomainException(DomainException):
    """representa en la respuesta un 404"""
    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message, cause)


class HttpApiException(ApplicationException):
    """clase base para todas las exceptions HttpApiException"""
    def __init__(self, message: str, cause: Optional[Exception] = None, status_code: Optional[int] = None) -> None:
        super().__init__(message, cause)
        self.status_code = status_code


class HttpApiRetryException(HttpApiException):
    """clase para todos los reintentos de HttpApiException"""
    def __init__(self, message: str, cause: Optional[Exception] = None, status_code: Optional[int] = None, retry_count: int = 0) -> None:
        super().__init__(message, cause, status_code)
        self.retry_count = retry_count


class HTTPApiStatusError(HttpApiException):
    """clase que representa el status code devuelto por httpx y que tiene un status code asociado"""
    def __init__(self, message: str, status_code: int, cause: Optional[Exception] = None) -> None:
        super().__init__(message, cause, status_code)


def setup_exception_logger(name: str = "application_exceptions", 
                          filename: str = "exceptions.log",
                          level: int = logging.ERROR) -> logging.Logger:
    """Configura un logger específico para las excepciones de la aplicación"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    if not logger.handlers:
        file_handler = logging.FileHandler(filename, encoding='utf-8')
        file_handler.setLevel(level)
        
        class UTCFormatter(logging.Formatter):
            converter = datetime.utcfromtimestamp
            def formatTime(self, record, datefmt=None):
                dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        
        formatter = UTCFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.propagate = False
    
    return logger


if __name__ == "__main__":
    import sys

    # Forzar UTF-8 en salida estándar y de errores
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')    
    print("✅ Consola configurada en UTF-8\n")

    log_filename = "exceptions.log"
    exception_logger = setup_exception_logger(filename=log_filename)
    
    try:
        try:
            raise ValueError("Error de validación en los datos")
        except ValueError as e:
            raise BadRequestDomainException("Los datos proporcionados no son válidos", cause=e)
    except BadRequestDomainException as domain_ex:
        try:
            raise HttpApiRetryException("Error al procesar la petición HTTP", cause=domain_ex, retry_count=3)
        except HttpApiRetryException as api_ex:            
            api_ex.log_exception(exception_logger)
            
    for handler in exception_logger.handlers:
        handler.flush()   
    
    try:
        raise ConnectionError("Error de conexión a la base de datos")
    except ConnectionError as conn_ex:
        try:
            raise HTTPApiStatusError("Error 500 en la API", status_code=500, cause=conn_ex)
        except HTTPApiStatusError as status_ex:            
            status_ex.log_exception(exception_logger)
    
    try:
        raise ConflictDomainException("Recurso ya existe - operación duplicada")
    except ConflictDomainException as conflict_ex:
        conflict_ex.log_exception(exception_logger)
    
    for handler in exception_logger.handlers:
        handler.flush()
