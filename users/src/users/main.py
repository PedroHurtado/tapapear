from common.infrastructure import document, Document, initialize_database
from uuid import uuid4
@document
class Bar(Document):
    name:str

bar = Bar(uuid4(),"Pedro")
bars = set([bar])
print(bars)
initialize_database("tapapear.json")