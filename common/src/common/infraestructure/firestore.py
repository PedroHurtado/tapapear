import logging
import asyncio
from uuid import UUID
from contextvars import ContextVar
from google.cloud import firestore
from google.cloud.firestore import AsyncClient, AsyncTransaction, AsyncDocumentReference
from google.oauth2.service_account import Credentials
from .documentnotfound import DocumentNotFound
from common.inflect import plural
from common.util import get_path
from typing import (
    Any,
    Callable,
    TypeVar,
    ParamSpec,
    Optional,
    Generic,
    Dict,
    Awaitable,
    TypeAlias,
    NewType,
    get_args,
    get_origin
)
from common.ioc import component, ProviderType, inject, deps
from common.mediator import ordered, CommandPipeLine, PipelineContext
from .document import Document, DocumentReference, MixinSerializer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Types para mejor tipado
P = ParamSpec("P")
T = TypeVar("T", bound=Document)

AsyncTransactionContext= NewType(
    "AsyncTransactionContext",
    ContextVar[Optional["AsyncTransaction"]],
)


db: AsyncClient = None
context_transaction: AsyncTransactionContext = ContextVar(
    "current_transaction", default=None
)


async def resolve_document_reference(doc_ref: AsyncDocumentReference) -> Dict[str, Any]:    
    path_parts = doc_ref.path.split("/")
    collection = path_parts[-2]
    doc_id = path_parts[-1]

    error = DocumentNotFound(doc_id, collection)
    return await RepositoryFirestore.__get(doc_ref, error)


def get_db() -> AsyncClient:
    if db is None:
        raise RuntimeError("DB no inicializada")
    return db


def get_document(path: str) -> AsyncDocumentReference:
    return get_db().document(path)


def get_current_transaction() -> Optional[AsyncTransaction]:
    """Obtiene la transacción actual del contexto"""
    return context_transaction.get()


def initialize_database(
    credentials_path: str,
    database: str = "(default)",
):
    global db
    credentials_path = get_path(credentials_path)
    cred = Credentials.from_service_account_file(credentials_path)
    db = AsyncClient(project=cred.project_id, credentials=cred, database=database)


def convert_document_references(data: Any) -> Any:
    """
    Función recursiva que convierte instancias de DocumentReference a AsyncDocumentReference
    en cualquier parte de la estructura de datos, usando pattern matching (Python 3.10+).
    """
    match data:
        case DocumentReference():
            return get_document(data.path)
        case dict():
            return {
                key: convert_document_references(value) for key, value in data.items()
            }
        case list():
            return [convert_document_references(item) for item in data]
        case tuple():
            return tuple(convert_document_references(item) for item in data)
        case set():
            return {convert_document_references(item) for item in data}
        case UUID():
            return str(data)
        case _:
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
    model_dict = model.model_dump(context={"is_root": True})
    return convert_document_references(model_dict)


async def to_document(
    data: Dict[str, Any], callback: Callable[[AsyncDocumentReference], Awaitable[Any]]
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

    match data:
        case AsyncDocumentReference():
            return await callback(data)
        case dict():
            return {k: await to_document(v, callback) for k, v in data.items()}
        case _:
            return data


class RepositoryFirestore(Generic[T]):
    """Repository base que maneja automáticamente las transacciones"""

    def __init_subclass__(cls, **kwargs):
        """Captura el tipo T cuando se define una subclase"""
        super().__init_subclass__(**kwargs)

        # Buscar en todas las bases para encontrar RepositoryFirestore[ConcreteType]
        for base in cls.__orig_bases__:
            origin = get_origin(base)
            if origin is RepositoryFirestore:
                args = get_args(base)
                if args:
                    cls._document_type = args[0]
                    break
        else:
            # Si no se encuentra, buscar en las bases de las bases (herencia múltiple)
            for base in cls.__mro__:
                if hasattr(base, "__orig_bases__"):
                    for orig_base in base.__orig_bases__:
                        origin = get_origin(orig_base)
                        if origin is RepositoryFirestore:
                            args = get_args(orig_base)
                            if args:
                                cls._document_type = args[0]
                                return

    @inject
    def __init__(self, db: AsyncClient = deps(AsyncClient)):
        # Validar que la clase tenga el tipo capturado
        if not hasattr(self.__class__, "_document_type"):
            raise ValueError(
                f"No se pudo determinar el tipo de documento para {self.__class__.__name__}. "
                f"Asegúrate de declarar la clase como: class {self.__class__.__name__}(RepositoryFirestore[TuTipo])"
            )

        cls = self.__class__._document_type

        if not issubclass(cls, Document):
            raise ValueError(
                f"La clase {cls.__name__} debe ser una subclase de Document"
            )

        self._cls = cls
        self._collection_name = plural(cls.__name__.lower())
        self._db = db

    def __get_collection(self):
        return self._db.collection(self._collection_name)

    @inject
    async def create(
        self,
        document: T,
        transaction: Optional[AsyncTransaction] = deps(AsyncTransaction),
    ) -> None:

        doc_ref = self.__get_collection().document(str(document.id))

        data_with_meta = to_firestore(document)

        if transaction:
            transaction.create(doc_ref, data_with_meta)
        else:
            await doc_ref.create(data_with_meta)

        logger.debug(f"📝 Documento creado en {self._collection_name}: {doc_ref.id}")

    async def get(self, id: UUID, message: str = None) -> T:

        doc_ref = self.__get_collection().document(str(id))
        error = DocumentNotFound(id, self._cls.__name__, message)
        data = await RepositoryFirestore.__get(doc_ref, error)
        processed_data = await to_document(data, resolve_document_reference)
        return self._cls(**processed_data)
        

    @staticmethod
    @inject
    async def __get(
        doc_ref: AsyncDocumentReference,
        error: DocumentNotFound,
        transaction: Optional[AsyncTransaction] = deps(AsyncTransaction),
    ) -> dict:
           
        doc_snapshot = await doc_ref.get(transaction=transaction)
        if doc_snapshot.exists:
            return {"id": doc_snapshot.id, **doc_snapshot.to_dict()}
        raise error

    @inject
    async def update(
        self,
        document: T,
        transaction: Optional[AsyncTransaction] = deps(AsyncTransaction),
    ) -> None:

        doc_ref = self.__get_collection().document(str(document.id))

        update_data = to_firestore(document)
        if transaction:
            transaction.set(doc_ref, update_data)
        else:
            await doc_ref.set(update_data)

        logger.debug(
            f"📝 Documento actualizado en {self._collection_name}: {document.id}"
        )

    @inject
    async def delete(
        self, doc: T, transaction: Optional[AsyncTransaction] = deps(AsyncTransaction)
    ) -> None:
        """Elimina un documento"""

        doc_ref = self.__get_collection().document(str(doc.id))

        if transaction:
            # Usar transacción
            transaction.delete(doc_ref)
        else:
            # Operación directa
            await doc_ref.delete()

        logger.debug(f"🗑️ Documento eliminado de {self._collection_name}: {doc.id}")

    @inject
    async def find_by_field(
        self,
        field: str,
        value: Any,
        limit: Optional[int] = None,
        transaction: Optional[AsyncTransaction] = deps(AsyncTransaction),
    ) -> list[T]:
        _value = str(value) if isinstance(value, UUID) else value
        query = self.__get_collection().where(field, "==", _value)

        if limit:
            query = query.limit(limit)

        docs = query.stream(transaction=transaction)        

        return [
            self._cls(**await to_document({"id": doc.id, **doc.to_dict()}, resolve_document_reference))
            async for doc in docs
        ]


@component
@ordered(100)
class TransactionPipeLine(CommandPipeLine):
    def __init__(self, db: AsyncClient, ctx_tx: AsyncTransactionContext):
        self._db = db
        self._cts_tx = ctx_tx

    async def handler(
        self, context: PipelineContext, next_handler: Callable[[], Any]
    ) -> Any:

        async def tx_wrapper(tx: AsyncTransaction):
            token = self._cts_tx.set(tx)
            try:
                return await next_handler()
            finally:
                self._cts_tx.reset(token)

        result = await self._db.transaction()(tx_wrapper)()
        return result


component(AsyncClient, provider_type=ProviderType.FACTORY, factory=get_db)
component(
    AsyncTransaction,
    provider_type=ProviderType.FACTORY,
    factory=get_current_transaction,
)
component(
    AsyncTransactionContext,
    provider_type=ProviderType.OBJECT,
    value=context_transaction,
)