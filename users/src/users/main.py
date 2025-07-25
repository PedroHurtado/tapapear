from common.infraestructure import document, Document
from uuid import uuid4
@document
class Bar(Document):
    name:str

bar = Bar(uuid4(),"Pedro")
bars = set([bar])
print(bars)