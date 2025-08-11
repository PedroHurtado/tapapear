from dependency_injector.wiring import inject
def inject_dependencies(func):    
    return inject(func)