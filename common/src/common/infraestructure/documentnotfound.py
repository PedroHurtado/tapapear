class DocumentNotFound(Exception):
    def __init__(self, id: str, collection: str, message: str = None):
        if message is None:
            message = f"The document {id} does not exist in collection {collection}"
        super().__init__(message)
        self.id = id
        self.collection = collection
