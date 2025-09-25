from automapper import  mapper
from automapper.mapper import Mapper as _Mapper

from typing import NewType
from common.ioc import component, ProviderType

Mapper = NewType(
    "Mapper",
    _Mapper
)

def mapper_class(source:any,target:any):
    mapper.add(source,target)
    mapper.add(target,source)

component(Mapper,provider_type=ProviderType.OBJECT, value=mapper)



    