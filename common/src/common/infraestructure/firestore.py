import os
import functools
import logging
import asyncio
import traceback
import uuid
from uuid import UUID
from contextvars import ContextVar
from google.cloud import firestore
from google.cloud.firestore import AsyncClient, AsyncTransaction, AsyncDocumentReference
from google.oauth2.service_account import Credentials
from .documentnotfound import DocumentNotFound
from typing import (
    Any,
    Callable,
    TypeVar,
    ParamSpec,
    Optional,    
    Type,
    Generic,
    Dict,
    Awaitable
)
from abc import ABC, abstractmethod
from .document import Document,DocumentReference,MixinSerializer
from .firestore_util import get_db,get_document
from dataclasses import fields, is_dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Types para mejor tipado
P = ParamSpec("P")
T = TypeVar("T", bound=Document)

# Context variable para almacenar la transacción actual
_current_transaction: ContextVar[Optional[AsyncTransaction]] = ContextVar(
    "current_transaction", default=None
)


class TransactionManager:
    """Gestor de transacciones para Firestore - completamente transparente"""

    def __init__(self, db: firestore.AsyncClient):
        self.db = db

    async def execute_in_transaction(self, func: Callable, *args, **kwargs):
        """Ejecuta una función dentro de una transacción de forma transparente"""

        async def transaction_func(transaction: AsyncTransaction):
            # Establecer la transacción en el contexto
            token = _current_transaction.set(transaction)
            try:
                # Ejecutar la función original sin modificar sus parámetros
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            finally:
                # Limpiar el contexto
                _current_transaction.reset(token)

        try:
            logger.info("🔄 Iniciando transacción Firestore")
            result = await self.db.run_transaction(transaction_func)
            logger.info("✅ Transacción completada exitosamente")
            return result
        except Exception as e:
            logger.error(f"❌ Error en transacción: {str(e)}")
            logger.debug(f"Traceback completo: {traceback.format_exc()}")
            raise


# Instancia global del gestor
transaction_manager: Optional[TransactionManager] = None


def init_firestore_transactions(db: firestore.AsyncClient):
    """Inicializar el sistema de transacciones"""
    global transaction_manager
    transaction_manager = TransactionManager(db)


def get_current_transaction() -> Optional[AsyncTransaction]:
    """Obtiene la transacción actual del contexto"""
    return _current_transaction.get()


def transactional(func: Callable[P, T]) -> Callable[P, T]:
    """
    Decorador que ejecuta el método dentro de una transacción Firestore.

    El método decorado se ejecuta normalmente, sin necesidad de manejar
    transacciones explícitamente. Los repositories automáticamente usan
    la transacción activa.

    Usage:
        @transactional
        async def create_user(self, user_data: dict):
            # Tu código normal aquí, sin try/except ni manejo de transacciones
            await self.external_service.validate(user_data)
            user = await self.user_repository.create(user_data)
            await self.audit_repository.log_creation(user.id)
            return user
    """

    @functools.wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if transaction_manager is None:
            raise RuntimeError(
                "Sistema de transacciones no inicializado. "
                "Llama a init_firestore_transactions(db) en el startup de tu app"
            )

        # Si ya estamos en una transacción, ejecutar directamente
        if get_current_transaction() is not None:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

        # Ejecutar en nueva transacción
        return await transaction_manager.execute_in_transaction(func, *args, **kwargs)

    return wrapper




def convert_document_references(data: Any) -> Any:
    """
    Función recursiva que convierte instancias de DocumentReference a AsyncDocumentReference
    en cualquier parte de la estructura de datos.
    
    Args:
        data: Estructura de datos que puede contener DocumentReference en cualquier nivel
        
    Returns:
        La misma estructura con DocumentReference convertidos a AsyncDocumentReference
    """
    # Caso base: si es una instancia de DocumentReference, convertirla
    if isinstance(data, DocumentReference):
        return get_document(data.path)
    
    # Si es un diccionario, procesar recursivamente cada valor
    elif isinstance(data, dict):
        return {key: convert_document_references(value) for key, value in data.items()}
    
    # Si es una lista, procesar recursivamente cada elemento
    elif isinstance(data, list):
        return [convert_document_references(item) for item in data]
    
    # Si es una tupla, procesar recursivamente y mantener como tupla
    elif isinstance(data, tuple):
        return tuple(convert_document_references(item) for item in data)
    
    # Si es un set, procesar recursivamente y mantener como set
    elif isinstance(data, set):
        return {convert_document_references(item) for item in data}
    
    # Para cualquier otro tipo (primitivos como str, int, float, bool, None), devolver tal como está
    else:
        return data
  

def to_firestore(model: MixinSerializer) -> Dict[str, Any]:
    """
    Convierte un modelo Pydantic a un diccionario listo para Firestore,
    reemplazando DocumentReference por AsyncDocumentReference.
    
    Args:
        model: Instancia de un modelo Pydantic
        
    Returns:
        Diccionario con las referencias convertidas
    """
    model_dict = model.model_dump()
    return convert_document_references(model_dict)

async def my_callback(doc_ref: AsyncDocumentReference) -> Dict[str, Any]:
    # Extraer collection e id del path
    path_parts = doc_ref.path.split('/')
    collection = path_parts[-2]
    doc_id = path_parts[-1]
    
    error = DocumentNotFound(doc_id, collection)
    return await Repository.__get(doc_ref, error)

async def to_document(
    data: Dict[str, Any], 
    callback: Callable[[AsyncDocumentReference], Awaitable[Any]]
) -> Dict[str, Any]:
    """
    Convierte AsyncDocumentReference a otros objetos usando un callback async.
    Recorre la estructura una sola vez.
    
    Args:
        data: Diccionario de datos de Firestore
        callback: Función async que procesa cada AsyncDocumentReference encontrado
        
    Returns:
        Diccionario con las referencias convertidas
    """
    if isinstance(data, AsyncDocumentReference):
        return await callback(data)
    
    elif isinstance(data, dict):
        return {k: await to_document(v, callback) for k, v in data.items()}
    
    elif isinstance(data, list):
        return [await to_document(item, callback) for item in data]
    
    elif isinstance(data, tuple):
        converted = [await to_document(item, callback) for item in data]
        return tuple(converted)
    
    elif isinstance(data, set):
        converted = {await to_document(item, callback) for item in data}
        return converted
    
    else:
        return data



class Repository(Generic[T]):
    """Repository base que maneja automáticamente las transacciones"""

    def __init__(self, cls: Type[T], db: Optional[AsyncClient] = None):
        if not issubclass(cls, Document):
            raise ValueError(
                f"La clase {cls.__name__} debe ser una subclase de Document"
            )

        self._cls = cls
        self._collection_name = cls.__name__.lower()
        self._db = db or get_db()

    def __get_collection(self):
        return self._db.collection(self._collection_name)

    async def create(self, document: T) -> None:

        transaction = get_current_transaction()

        doc_ref = self.__get_collection().document(str(document.id))

        data_with_meta = to_firestore(document)

        if transaction:
            transaction.create(doc_ref, data_with_meta)
        else:
            await doc_ref.create(data_with_meta)

        logger.debug(f"📝 Documento creado en {self.collection_name}: {doc_ref.id}")

    async def get(self, id: UUID, message: str = None) -> T:
       
        doc_ref = self.__get_collection_ref().document(str(id))
        error = DocumentNotFound(id, self._cls.__name__, message)
        data =  await Repository.__get(doc_ref,error)
        return self._cls(**data)
    
    @staticmethod
    async def __get(doc_ref:AsyncDocumentReference, error:DocumentNotFound)->T:
        
        transaction = get_current_transaction()
        if transaction:
            doc_snapshot = await transaction.get(doc_ref)
        else:
            doc_snapshot = await doc_ref.get()

        if doc_snapshot.exists:
            return doc_snapshot.to_dict()
        
        raise error
        
    async def update(self, document: T) -> None:

        transaction = get_current_transaction()
        doc_ref = self.__get_collection_ref().documen(str(document.id))

        update_data = to_firestore(document)

        if transaction:
            transaction.update(doc_ref, update_data)
        else:
            # Operación directa
            await doc_ref.update(update_data)

        logger.debug(
            f"📝 Documento actualizado en {self.collection_name}: {document.id}"
        )

    async def delete(self, doc: T) -> None:
        """Elimina un documento"""
        transaction = get_current_transaction()
        doc_ref = self.__get_collection_ref().document(str(doc.id))

        if transaction:
            # Usar transacción
            transaction.delete(doc_ref)
        else:
            # Operación directa
            await doc_ref.delete()

        logger.debug(f"🗑️ Documento eliminado de {self.collection_name}: {doc.id}")

    async def find_by_field(
        self, field: str, value: Any, limit: Optional[int] = None
    ) -> list[T]:
        _value = str(value) if isinstance(value, UUID) else value
        query = self.__get_collection_ref().where(field, "==", _value)

        if limit:
            query = query.limit(limit)

        # Las consultas no se pueden hacer dentro de transacciones en Firestore
        # pero si necesitas consistencia, deberías hacer get_by_id de documentos específicos
        docs = await query.stream()
        return [self._cls(**to_document(doc.to_dict())) async for doc in docs]
