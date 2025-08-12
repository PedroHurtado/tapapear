from dependency_injector.wiring import inject as _inject
def inject(func):    
    return _inject(func)