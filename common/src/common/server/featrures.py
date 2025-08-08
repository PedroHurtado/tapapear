import glob
import os
import importlib.util
import inspect
from types import ModuleType
from typing import List, Tuple, Any


def get_feature_modules(
    features_dir: str = "features", router_var_name: str = "router"
) -> Tuple[List[Any], List[ModuleType]]:
    """
    Escanea la carpeta features y devuelve los routers y módulos encontrados.

    Args:
        features_dir: Carpeta raíz de las features.
        router_var_name: Nombre de la variable router a buscar en cada módulo.

    Returns:
        Una tupla (routers, modules):
            - routers: Lista de objetos APIRouter encontrados.
            - modules: Lista de módulos cargados dinámicamente.
    """
    routers = []
    modules = []

    # Obtener el directorio desde donde se llama la función
    caller_frame = inspect.currentframe().f_back
    caller_file = caller_frame.f_globals["__file__"]
    caller_dir = os.path.dirname(os.path.abspath(caller_file))

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
            module_name = os.path.splitext(filename)[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                modules.append(module)

                # Si el módulo tiene un router, lo añadimos
                if hasattr(module, router_var_name):
                    routers.append(getattr(module, router_var_name))

        except Exception as e:
            print(f"Error al importar {file_path}: {e}")
            continue

    return routers, modules
