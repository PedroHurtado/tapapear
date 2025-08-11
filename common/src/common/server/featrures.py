import glob
import os
import importlib.util
from typing import List, Tuple, Any


def get_feature_modules(
    base_path: str,
    features_dir: str = "features",
    router_var_name: str = "router"
) -> Tuple[List[Any], List[str]]:
    """
    Escanea la carpeta features y devuelve los routers y nombres de módulos encontrados.

    Args:
        base_path: La ruta base del proyecto, de donde se cargará el directorio 'features'.
        features_dir: Nombre de la carpeta de features.
        router_var_name: Nombre de la variable router a buscar en cada módulo.

    Returns:
        Una tupla (routers, module_names):
            - routers: Lista de objetos APIRouter encontrados.
            - module_names: Lista de nombres de módulos (str) para dependency_injector.
    """
    routers = []
    module_names = []

    # Se usa la ruta base proporcionada en lugar de intentar inferirla
    features_path = os.path.join(base_path, features_dir)

    if not os.path.exists(features_path):
        print(f"Advertencia: El directorio {features_path} no existe")
        return [], []

    # Obtener el nombre del paquete base a partir de la ruta
    # Esto asume que el nombre del directorio es el nombre del paquete
    package_prefix = os.path.basename(base_path)

    pattern = os.path.join(features_path, "**", "*.py")
    python_files = glob.glob(pattern, recursive=True)

    for file_path in python_files:
        filename = os.path.basename(file_path)
        if filename.startswith("__") or filename.startswith("test_"):
            continue

        try:
            # Construir el nombre completo del módulo
            rel_path = os.path.relpath(file_path, base_path)
            module_path_parts = rel_path.replace(os.sep, '.').split('.')[:-1]
            full_module_name = f"{package_prefix}.{'.'.join(module_path_parts)}"
            
            spec = importlib.util.spec_from_file_location(full_module_name, file_path)

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                module_names.append(full_module_name)

                if hasattr(module, router_var_name):
                    routers.append(getattr(module, router_var_name))

        except Exception as e:
            print(f"Error al importar {file_path}: {e}")
            continue

    return routers, module_names
