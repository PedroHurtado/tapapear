import logging
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
    get_origin,
)
from common.ioc import component, ProviderType, inject, deps
from common.mediator import ordered, CommandPipeLine, PipelineContext
from .document import Document, DocumentReference, MixinSerializer

# OpenTelemetry
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Types para mejor tipado
P = ParamSpec("P")
T = TypeVar("T", bound=Document)

AsyncTransactionContext = NewType(
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
    """
    model_dict = model.model_dump(context={"is_root": True})
    return convert_document_references(model_dict)


async def to_document(
    data: Dict[str, Any], callback: Callable[[AsyncDocumentReference], Awaitable[Any]]
) -> Dict[str, Any]:
    """
    Convierte AsyncDocumentReference a otros objetos usando un callback async.
    Recorre la estructura una sola vez.
    """
    match data:
        case AsyncDocumentReference():
            return await callback(data)
        case dict():
            return {k: await to_document(v, callback) for k, v in data.items()}
        case _:
            return data


# --- MIXIN DE INSTRUMENTACIÓN ---

class FirestoreTracingMixin:
    def _start_span(self, operation: str, **attributes):
        span_name = f"infraestructure.firestore.{operation}.{self._collection_name}"
        ctx_manager = tracer.start_as_current_span(span_name,record_exception=True)
        span = ctx_manager.__enter__()  # activa el contexto y devuelve el span real

        # Guardamos el context manager para cerrarlo en _end_span
        span._ctx_manager = ctx_manager  

        # Atributos comunes
        span.set_attribute("db.system", "firestore")
        span.set_attribute("db.collection", self._collection_name)
        span.set_attribute("db.operation", operation)
        span.set_attribute("db.name", getattr(self._db, "_database", "(default)"))
        span.set_attribute("repository.class", self.__class__.__name__)
        span.set_attribute("repository.model", self._cls.__name__)

        # Atributos específicos
        for k, v in attributes.items():
            if v is not None:
                span.set_attribute(k, v)

        return span

    def _end_span(self, span, error: Optional[Exception] = None):
        if error:
            span.record_exception(error)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(error)))
        else:
            span.set_status(trace.StatusCode.OK)
        # Cerramos el context manager para liberar el span
        span._ctx_manager.__exit__(None, None, None)



# --- REPOSITORIO ---

class RepositoryFirestore(FirestoreTracingMixin, Generic[T]):
    """Repository base que maneja automáticamente las transacciones"""

    def __init_subclass__(cls, **kwargs):
        """Captura el tipo T cuando se define una subclase"""
        super().__init_subclass__(**kwargs)

        for base in cls.__orig_bases__:
            origin = get_origin(base)
            if origin is RepositoryFirestore:
                args = get_args(base)
                if args:
                    cls._document_type = args[0]
                    break
        else:
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
        span = self._start_span(
            "create",
            db_document_id=str(document.id),
            transaction_active=transaction is not None,
        )
        error: Optional[Exception] = None
        try:
            doc_ref = self.__get_collection().document(str(document.id))
            data_with_meta = to_firestore(document)

            if transaction is not None:
                transaction.create(doc_ref, data_with_meta)
            else:
                await doc_ref.create(data_with_meta)

            logger.debug(f"📝 Documento creado en {self._collection_name}: {doc_ref.id}")
        except Exception as e:
            error = e
            raise
        finally:
            self._end_span(span, error)

    async def get(self, id: UUID, message: str = None) -> T:
        span = self._start_span(
            "get",
            db_document_id=str(id),
        )
        error: Optional[Exception] = None
        try:
            doc_ref = self.__get_collection().document(str(id))
            error_obj = DocumentNotFound(id, self._cls.__name__, message)
            data = await RepositoryFirestore.__get(doc_ref, error_obj)
            processed_data = await to_document(data, resolve_document_reference)
            return self._cls(**processed_data)
        except Exception as e:
            error = e
            raise
        finally:
            self._end_span(span, error)

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
        span = self._start_span(
            "update",
            db_document_id=str(document.id),
            transaction_active=transaction is not None,
        )
        error: Optional[Exception] = None
        try:
            doc_ref = self.__get_collection().document(str(document.id))
            update_data = to_firestore(document)
            if transaction is not None:
                transaction.set(doc_ref, update_data)
            else:
                await doc_ref.set(update_data)

            logger.debug(
                f"📝 Documento actualizado en {self._collection_name}: {document.id}"
            )
        except Exception as e:
            error = e
            raise
        finally:
            self._end_span(span, error)

    @inject
    async def delete(
        self, doc: T, transaction: Optional[AsyncTransaction] = deps(AsyncTransaction)
    ) -> None:
        span = self._start_span(
            "delete",
            db_document_id=str(doc.id),
            transaction_active=transaction is not None,
        )
        error: Optional[Exception] = None
        try:
            doc_ref = self.__get_collection().document(str(doc.id))
            if transaction is not None:
                transaction.delete(doc_ref)
            else:
                await doc_ref.delete()

            logger.debug(f"🗑️ Documento eliminado de {self._collection_name}: {doc.id}")
        except Exception as e:
            error = e
            raise
        finally:
            self._end_span(span, error)

    @inject
    async def find_by_field(
        self,
        field: str,
        value: Any,
        limit: Optional[int] = None,
        transaction: Optional[AsyncTransaction] = deps(AsyncTransaction),
    ) -> list[T]:
        span = self._start_span(
            "query",
            db_query_field=field,
            db_query_value=str(value) if isinstance(value, UUID) else value,
            db_query_limit=limit,
            transaction_active=transaction is not None,
        )
        error: Optional[Exception] = None
        try:
            _value = str(value) if isinstance(value, UUID) else value
            query = self.__get_collection().where(field, "==", _value)
            if limit:
                query = query.limit(limit)
            docs = query.stream(transaction=transaction)
            results = [
                self._cls(
                    **await to_document(
                        {"id": doc.id, **doc.to_dict()}, resolve_document_reference
                    )
                )
                async for doc in docs
            ]
            span.set_attribute("db.query.result_count", len(results))
            return results
        except Exception as e:
            error = e
            raise
        finally:
            self._end_span(span, error)


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
            except Exception:
                raise
            finally:
                self._cts_tx.reset(token)

        async with self._db.transaction() as tx:
            result = await tx_wrapper(tx)

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
