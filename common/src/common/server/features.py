import glob
import os
import importlib.util
import sys
from typing import List, Tuple, Any


def get_feature_routers(
    features_path: str = "features",
    router_var_name: str = "router"
) -> List[Any]:
    """
    Escanea una ruta de features específica y devuelve los routers y nombres de módulos encontrados.
    
    Args:
        features_path: Ruta en formato punto (ej: "customers.features")
        router_var_name: Nombre de la variable router a buscar en cada módulo.

    Returns:       
            - routers: Lista de objetos APIRouter encontrados.        
    """
    routers = []    

    # Convertir la notación de puntos a ruta de sistema
    

    # Buscar la ruta física del directorio features
    base_path = None

    # Opción 1: desde __main__
    import __main__
    if hasattr(__main__, '__file__') and __main__.__file__:
        main_dir = os.path.dirname(os.path.abspath(__main__.__file__))
        features_path_fs = features_path.replace(".", os.sep)
        potential_path = os.path.join(main_dir, features_path_fs)
        if os.path.exists(potential_path):
            base_path = potential_path    
    
    if not base_path:
        print(f"Error: No se pudo encontrar el directorio de features: {features_path}")
        return [], []

    print(f"Escaneando features en: {base_path}")    

    # Buscar todos los archivos Python en el directorio features
    pattern = os.path.join(base_path, "**", "*.py")
    python_files = glob.glob(pattern, recursive=True)

    for file_path in python_files:
        filename = os.path.basename(file_path)

        # Ignorar __init__.py, tests, etc.
        if filename.startswith("__") or filename.startswith("test_"):
            continue

        try:
            # Ruta relativa desde base_path
            rel_path = os.path.relpath(file_path, base_path)
            module_path_parts = rel_path.replace(os.sep, '.').split('.')[:-1]
            full_module_name = f"{features_path}.{'.'.join(module_path_parts)}"

            print(f"Intentando importar: {full_module_name} desde {file_path}")

            spec = importlib.util.spec_from_file_location(full_module_name, file_path)

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[full_module_name] = module
                spec.loader.exec_module(module)

                

                if hasattr(module, router_var_name):
                    routers.append(getattr(module, router_var_name))
                    print(f"✓ Router encontrado en {full_module_name}")
                else:
                    print(f"⚠ No se encontró '{router_var_name}' en {full_module_name}")

        except Exception as e:
            print(f"✗ Error al importar {file_path}: {e}")
            continue

    print(f"Total de routers encontrados: {len(routers)}")    

    return routers
