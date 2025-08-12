import inflect

p = inflect.engine()

def plural(name:str)->str:
    return p.plural(name)