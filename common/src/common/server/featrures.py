import glob
import os
import importlib.util
import inspect
from typing import List, Tuple, Any


def get_feature_modules(
    features_dir: str = "features", router_var_name: str = "router"
) -> Tuple[List[Any], List[str]]:
    """
    Escanea la carpeta features y devuelve los routers y nombres de módulos encontrados.

    Args:
        features_dir: Carpeta raíz de las features.
        router_var_name: Nombre de la variable router a buscar en cada módulo.

    Returns:
        Una tupla (routers, module_names):
            - routers: Lista de objetos APIRouter encontrados.
            - module_names: Lista de nombres de módulos (str) para dependency_injector.
    """
    routers = []
    module_names = []

    # Obtener el directorio desde donde se llama la función
    caller_frame = inspect.currentframe().f_back
    caller_file = caller_frame.f_globals["__file__"]
    caller_dir = os.path.dirname(os.path.abspath(caller_file))

    # Obtener el nombre del paquete actual para construir nombres completos
    caller_module = caller_frame.f_globals.get("__name__", "")
    if caller_module == "__main__":
        # Si se llama desde main.py, asumir que estamos en el paquete raíz
        package_prefix = "customer"
    else:
        # Extraer el paquete base del módulo que llama
        package_parts = caller_module.split(".")
        package_prefix = package_parts[0] if package_parts else "customer"

    features_path = os.path.join(caller_dir, features_dir)

    if not os.path.exists(features_path):
        print(f"Advertencia: El directorio {features_path} no existe")
        return [], []

    pattern = os.path.join(features_path, "**", "*.py")
    python_files = glob.glob(pattern, recursive=True)

    for file_path in python_files:
        filename = os.path.basename(file_path)
        if filename.startswith("__") or filename.startswith("test_"):
            continue

        try:
            # Construir el nombre completo del módulo
            rel_path = os.path.relpath(file_path, caller_dir)
            module_path_parts = rel_path.replace(os.sep, '.').split('.')[:-1]  # Remover .py
            full_module_name = f"{package_prefix}.{'.'.join(module_path_parts)}"
            
            spec = importlib.util.spec_from_file_location(full_module_name, file_path)

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Agregar el nombre del módulo (no el objeto)
                module_names.append(full_module_name)

                # Si el módulo tiene un router, lo añadimos
                if hasattr(module, router_var_name):
                    routers.append(getattr(module, router_var_name))

        except Exception as e:
            print(f"Error al importar {file_path}: {e}")
            continue

    return routers, module_names