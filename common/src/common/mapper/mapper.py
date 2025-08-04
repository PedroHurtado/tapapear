from automapper import mapper, Mapper

def get_mapper(source:any,target:any)->Mapper:
    mapper.add(source,target)
    mapper.add(target,source)
    return mapper