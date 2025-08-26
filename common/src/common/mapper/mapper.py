from automapper import mapper, Mapper
from common.ioc import component, ProviderType

component(Mapper,provider_type=ProviderType.OBJECT, value=mapper)

def register_class(source:any,target:any):
    mapper.add(source,target)
    mapper.add(target,source)




    