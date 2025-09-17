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
    List,
    Tuple,
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
from .document import Document, DocumentReference, CollectionReference, MixinSerializer

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



def generate_firestore_commands(data: dict, db):
    """
    Extrae CollectionReference del JSON y genera comandos Firestore ordenados por nivel jerárquico.
    """
    commands = []
    
    def create_doc_ref_from_path(path: str):
        """Crea AsyncDocumentReference usando db.collection().document() por niveles"""
        path_parts = path.split('/')
        doc_ref = db
        
        for i in range(0, len(path_parts), 2):
            if i < len(path_parts):
                doc_ref = doc_ref.collection(path_parts[i])
            if i + 1 < len(path_parts):
                doc_ref = doc_ref.document(path_parts[i + 1])
        
        return doc_ref
    
    def process_object(obj):
        """Procesa recursivamente el objeto buscando CollectionReference"""
        
        if isinstance(obj, dict):
            # Verificar si este dict representa un documento con CollectionReference como id
            if 'id' in obj and isinstance(obj['id'], CollectionReference):
                collection_ref = obj['id']
                
                # Crear el documento de Firestore
                doc_ref = create_doc_ref_from_path(collection_ref.path)
                
                # Extraer los datos (todo excepto el 'id')
                doc_data = {}
                for key, value in obj.items():
                    if key == 'id':
                        continue  # Skip CollectionReference id
                    else:
                        # Procesar recursivamente para limpiar subcollections anidadas
                        processed_value = process_object(value)
                        if processed_value is not None:
                            doc_data[key] = processed_value
                
                # Convertir DocumentReference a AsyncDocumentReference en los datos
                doc_data = convert_document_references(doc_data)
                
                # Calcular nivel jerárquico
                level = len(collection_ref.path.split('/')) // 2
                commands.append((level, doc_ref, doc_data))
                
                # Retornar None para indicar que este nivel se procesó como subcollection
                return None
            
            else:
                # Dict normal, procesar recursivamente
                result = {}
                for key, value in obj.items():
                    processed_value = process_object(value)
                    if processed_value is not None:
                        result[key] = processed_value
                return result
        
        elif isinstance(obj, (list, set)):
            # Procesar listas/sets
            result = []
            for item in obj:
                processed_item = process_object(item)
                if processed_item is not None:
                    result.append(processed_item)
            
            return set(result) if isinstance(obj, set) else result
        
        else:
            # Tipos primitivos
            return obj
    
    # Procesar todos los datos
    process_object(data)
    
    # Ordenar comandos por nivel jerárquico
    commands.sort(key=lambda x: x[0])
    
    return [(doc_ref, doc_data) for level, doc_ref, doc_data in commands]


def convert_document_references(data):
    """
    Convierte DocumentReference a AsyncDocumentReference, ignora CollectionReference
    """
    if isinstance(data, DocumentReference):
        return get_document(data.path)
    elif isinstance(data, CollectionReference):
        # Las CollectionReference se ignoran (ya procesadas por generate_firestore_commands)
        return None
    elif isinstance(data, dict):
        result = {}
        for key, value in data.items():
            converted = convert_document_references(value)
            if converted is not None:
                result[key] = converted
        return result
    elif isinstance(data, (list, tuple)):
        result = []
        for item in data:
            converted = convert_document_references(item)
            if converted is not None:
                result.append(converted)
        return tuple(result) if isinstance(data, tuple) else result
    elif isinstance(data, set):
        result = set()
        for item in data:
            converted = convert_document_references(item)
            if converted is not None:
                result.add(converted)
        return result
    elif isinstance(data, UUID):
        return str(data)
    else:
        return data


def to_firestore(model):
    """
    Convierte un modelo Pydantic a un diccionario listo para Firestore.
    Filtra las subcollections que se procesan por separado.
    """
    model_dict = model.model_dump(context={"is_root": True})
    return convert_document_references(model_dict)


def remove_subcollections(data):
    """
    Remueve objetos que contienen CollectionReference como id del diccionario principal
    """
    if isinstance(data, dict):
        if 'id' in data and isinstance(data['id'], CollectionReference):
            # Este es un documento que debe ir en subcollection, no en el documento principal
            return None
        
        result = {}
        for key, value in data.items():
            cleaned_value = remove_subcollections(value)
            if cleaned_value is not None:
                result[key] = cleaned_value
        return result
    
    elif isinstance(data, (list, set)):
        result = []
        for item in data:
            cleaned_item = remove_subcollections(item)
            if cleaned_item is not None:
                result.append(cleaned_item)
        return set(result) if isinstance(data, set) else result
    
    else:
        return data


def to_firestore_main_document(model):
    """
    Convierte solo el documento principal (sin subcollections) para Firestore
    """
    model_dict = model.model_dump(context={"is_root": True})
    # Remover subcollections
    cleaned_dict = remove_subcollections(model_dict)
    # Convertir referencias normales
    return convert_document_references(cleaned_dict)


def prepare_all_firestore_commands(document, collection_ref, db):
    """
    Prepara TODOS los comandos Firestore (documento principal + subcollections)
    ordenados por nivel jerárquico
    """
    # Obtener datos serializados
    model_dict = document.model_dump(context={"is_root": True})
    
    # Extraer comandos para subcollections
    subcollection_commands = generate_firestore_commands(model_dict, db)
    
    # Preparar documento principal (nivel 0)
    main_doc_ref = collection_ref.document(str(document.id))
    main_data = to_firestore_main_document(document)
    
    # Combinar: principal primero, luego subcollections (ya están ordenadas por nivel)
    all_commands = [(main_doc_ref, main_data)] + subcollection_commands
    
    return all_commands


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
    def _start_span(self, operation: str, *, db_statement: Optional[str] = None):
        span_name = f"infrastructure.firestore.{operation}.{self._collection_name}"
        ctx_manager = tracer.start_as_current_span(
            span_name, kind=trace.SpanKind.CLIENT
        )
        span = ctx_manager.__enter__()  # activa el contexto y devuelve el span real
        span._ctx_manager = ctx_manager  # guardamos para cerrarlo en _end_span

        # --- Atributos comunes (OTel DB semantic conventions) ---
        span.set_attribute("db.system", "firestore")
        span.set_attribute("db.name", getattr(self._db, "_database", "(default)"))
        span.set_attribute("db.namespace", self._db.project)  # projectId de GCP
        span.set_attribute("db.collection.name", self._collection_name)
        span.set_attribute("db.operation", operation)
        span.set_attribute(
            "code.namespace",
            f"{self.__class__.__module__}.{self.__class__.__name__}",
        )
        span.set_attribute(
            "repository.model", f"{self.__class__.__module__}.{self._cls.__name__}"
        )

        # --- Statement (pseudo-SQL) ---
        if db_statement:
            span.set_attribute("db.statement", db_statement)

        return span

    def _end_span(self, span, error: Optional[Exception] = None):
        if error:
            span.record_exception(error)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(error)))
        else:
            span.set_status(trace.Status(trace.StatusCode.OK))
        span._ctx_manager.__exit__(None, None, None)


# --- REPOSITORIO ---


class RepositoryFirestore(FirestoreTracingMixin, Generic[T]):
    """Repository base que maneja automáticamente las transacciones"""

    def __init_subclass__(cls, **kwargs):
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
        statement = (
            f"INSERT INTO {self._collection_name} (id={document.id}) "
            f"[transaction={transaction is not None}]"
        )
        span = self._start_span("insert", db_statement=statement)
        error: Optional[Exception] = None
        try:
            # Preparar todos los comandos (principal + subcollections)
            all_commands = prepare_all_firestore_commands(document, self.__get_collection(), self._db)
            
            # Crear todos los documentos en orden
            if transaction is not None:
                for doc_ref, data in all_commands:
                    transaction.create(doc_ref, data)
            else:
                for doc_ref, data in all_commands:
                    await doc_ref.create(data)

            logger.debug(
                f"📝 Documentos creados en {self._collection_name}: {document.id} "
                f"+ {len(all_commands)-1} subcollections"
            )
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
        statement = (
            f"UPDATE {self._collection_name} SET ... WHERE id={document.id} "
            f"[transaction={transaction is not None}]"
        )
        span = self._start_span("update", db_statement=statement)
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
        statement = (
            f"DELETE FROM {self._collection_name} WHERE id={doc.id} "
            f"[transaction={transaction is not None}]"
        )
        span = self._start_span("delete", db_statement=statement)
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
        _value = str(value) if isinstance(value, UUID) else value
        statement = (
            f"SELECT * FROM {self._collection_name} WHERE {field}={_value}"
            + (f" LIMIT {limit}" if limit else "")
            + f" [transaction={transaction is not None}]"
        )
        span = self._start_span("find", db_statement=statement)
        error: Optional[Exception] = None
        try:       
            
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
@ordered(1000)
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
