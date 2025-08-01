import os
from uuid import UUID
from google.oauth2.service_account import Credentials
from google.cloud import firestore
from google.cloud.firestore import (
    AsyncClient, AsyncTransaction, AsyncDocumentReference
)

db: AsyncClient = None

def get_db() -> AsyncClient:
    if db is None:
        raise RuntimeError("DB no inicializada")
    return db

def get_document(collection_name:str,id:UUID)->AsyncDocumentReference:
    get_db().collection(collection_name).document(str(id))

def initialize_database(
    credentials_path: str,
    database: str = "(default)",
):
    global db
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
    cred = Credentials.from_service_account_file(credentials_path)
    db = AsyncClient(project=cred.project_id, credentials=cred, database=database)
