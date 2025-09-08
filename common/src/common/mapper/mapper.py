from automapper import mapper, Mapper
from automapper import Mapper as _Mapper, mapper
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



    