import glob
import os
import importlib.util
from typing import List, Any


def get_routers(features_dir: str = "features", router_var_name: str = "router") -> List[Any]:
    """
    Escanea la carpeta features y devuelve los routers encontrados.
    
    Args:
        features_dir: Nombre de la carpeta features (por defecto "features")
        router_var_name: Nombre de la variable router a buscar (por defecto "router")
    
    Returns:
        Lista con los objetos router encontrados
    """
    routers = []
    
    # Obtener el directorio desde donde se llama la función
    import inspect
    caller_frame = inspect.currentframe().f_back
    caller_file = caller_frame.f_globals['__file__']
    caller_dir = os.path.dirname(os.path.abspath(caller_file))
    
    # Construir la ruta a features
    features_path = os.path.join(caller_dir, features_dir)
    
    # Verificar que el directorio existe
    if not os.path.exists(features_path):
        print(f"Warning: El directorio {features_path} no existe")
        return routers
    
    # Buscar todos los archivos .py recursivamente
    pattern = os.path.join(features_path, "**", "*.py")
    python_files = glob.glob(pattern, recursive=True)
    print(f"Archivos encontrados: {python_files}")  # Debug line
    
    for file_path in python_files:
        # Saltar archivos __init__.py y archivos de test
        filename = os.path.basename(file_path)
        if filename.startswith("__") or filename.startswith("test_"):
            continue
            
        try:
            # Cargar el módulo dinámicamente
            module_name = os.path.splitext(filename)[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Verificar si tiene la variable router y agregarla
                if hasattr(module, router_var_name):
                    router_obj = getattr(module, router_var_name)
                    routers.append(router_obj)
                        
        except Exception:
            # Silenciosamente continuar si hay errores al importar
            continue
    
    return routers


