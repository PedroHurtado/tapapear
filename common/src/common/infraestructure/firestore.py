import os
import functools
import logging
import asyncio
import traceback
import uuid
from uuid import UUID
from contextvars import ContextVar
from google.cloud import firestore
from google.cloud.firestore import (
    AsyncClient, AsyncTransaction, AsyncDocumentReference
)
from google.oauth2.service_account import Credentials
from .documentnotfound import DocumentNotFound
from typing import (
    Any,
    Callable,
    TypeVar,
    ParamSpec,
    Optional,
    get_origin,
    get_args,
    Union,
    Type,
    Generic,
)
from abc import ABC, abstractmethod
from .document import Document
from .firestore_util import get_db
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



def resolve_real_type(annotated_type):
    """
    Si el tipo es Optional[Collection[T]], devuelve (collection_type, T).
    Si el tipo es Collection[T], devuelve (collection_type, T).
    """
    origin = get_origin(annotated_type)
    args = get_args(annotated_type)

    # Caso: Optional[Set[T]] → Union[Set[T], None]
    if origin is Union and type(None) in args:
        actual_type = [a for a in args if a is not type(None)][0]
        return resolve_real_type(actual_type)

    # Caso: Set[T], List[T], etc.
    if origin in (list, set, tuple) and args:
        return origin, args[0]

    return None, None

def _resolve_inner_type(tp):
    origin = get_origin(tp)  # obtiene la "clase base" genérica, ej. list o set
    if origin in (list, set):
        args = get_args(tp)  # obtiene los parámetros genéricos, ej. [Comment] o [Tag]
        if args:
            return args[0]  # devuelve el tipo interno (el primer parámetro genérico)
    return None  # si no es list o set o no tiene parámetros, devuelve None

def to_dict(obj: T, db: AsyncClient = None) -> dict:
    result = {}
    for name, field in obj:
        value = getattr(obj, name)
        meta = field.metadata

        # ID (posiblemente UUID)
        if meta.get("id"):
            result[name] = str(value) if isinstance(value, UUID) else value

        # Subcolecciones (List[Document] o Set[Document])
        elif "subcollection" in meta:
            if value is None:
                result[name] = None
            else:
                inner_type = _resolve_inner_type(field.annotation)
                if inner_type:
                    result[name] = [to_dict(item, db=db) for item in value]
                else:
                    raise TypeError(f"Unsupported collection type for field '{name}'")

        # Referencias a otros documentos
        elif meta.get("reference"):
            if value is None:
                result[name] = None
            else:
                ref_id = getattr(value, "id", None)
                if not ref_id:
                    raise ValueError(f"La referencia en '{name}' no tiene 'id' definido")
                if not db:
                    raise ValueError("El parámetro 'db' (Firestore client) es necesario para serializar referencias")
                collection = meta.get("reference") or name  # usar valor explícito o nombre del campo
                result[name] = db.collection(collection).document(str(ref_id))

        # Resto de campos normales
        else:
            result[name] = str(value) if isinstance(value, UUID) else value

    return result






def from_dict(cls: Type[T], data: dict)->T:    
    
    if not issubclass(cls, Document):
        raise TypeError(f"{cls} is not a Document")

    kwargs = {}
    for f in cls.model_fields:
        value = data.get(f.name)
        meta = f.metadata

        if meta.get("id"):
            kwargs[f.name] = uuid.UUID(value) if isinstance(value, str) else value

        elif "subcollection" in meta:
            if value is None:
                kwargs[f.name] = None
            else:
                collection_type, item_type = resolve_real_type(f.type)
                if collection_type:
                    kwargs[f.name] = collection_type(
                        from_dict(item_type, item) for item in value
                    )
                else:
                    raise TypeError(f"Unsupported collection type for field '{f.name}'")

        elif meta.get("reference"):
            if value is None:
                kwargs[f.name] = None
            else:
                # value es DocumentReference
                doc_snapshot = value.get()
                doc_data = doc_snapshot.to_dict()
                ref_cls = f.type
                # Solo nivel 1: inyectar también el ID
                doc_data["id"] = doc_snapshot.id
                kwargs[f.name] = ref_cls(**doc_data)

        else:
            # 🚀 Conversión automática de UUIDs si el tipo declarado es uuid.UUID
            if isinstance(value, str) and f.type is uuid.UUID:
                kwargs[f.name] = uuid.UUID(value)
            else:
                kwargs[f.name] = value


    return cls(**kwargs)





class Repository(Generic[T]):
    """Repository base que maneja automáticamente las transacciones"""

    def __init__(
        self, cls: Type[T], db: Optional[AsyncClient] = None
    ):

         
        if not issubclass(cls, Document):
            raise ValueError(f"La clase {cls.__name__} debe ser una subclase de Document")
        
        self._cls = cls        
        self._collection_name = cls.__name__.lower()
            
        self._db = db or get_db()

    def __get_collection(self):
        return self._db.collection(self._collection_name)

    async def create(self, document: T) -> None:

        transaction = get_current_transaction()
        
        doc_ref = self.__get_collection().document(str(document.id))

        data_with_meta = to_dict(document, self.db)

        if transaction:
            transaction.create(doc_ref, data_with_meta)
        else:
            await doc_ref.create(data_with_meta)

        logger.debug(f"📝 Documento creado en {self.collection_name}: {doc_ref.id}")

    async def get(self, id: UUID, message:str=None) -> T:

        transaction = get_current_transaction()
        doc_ref = self.__get_collection_ref().document(str(id))

        if transaction:
            doc_snapshot = await transaction.get(doc_ref)
        else:
            doc_snapshot = await doc_ref.get()

        if doc_snapshot.exists:
            return from_dict(self._cls, doc_snapshot.to_dict())
        
        raise DocumentNotFound(id, self._cls.__name__, message)
        

    async def update(self, document: T) -> None:

        transaction = get_current_transaction()
        doc_ref = self.__get_collection_ref().documen(str(document.id))

        update_data = to_dict(document, self._db)

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
        return [from_dict(self._cls, doc.to_dict()) async for doc in docs]

