from pydantic import BaseModel
from abc import ABC, abstractmethod    

from pydantic import BaseModel

from pydantic import BaseModel, ConfigDict
from inspect import signature


class ValueObject(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra='forbid'
    )
   

