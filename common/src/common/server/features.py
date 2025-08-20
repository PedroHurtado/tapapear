import glob
import os
import sys
import importlib.util

from typing import List, Tuple, Any
from pathlib import Path
from common.util import get_path


def get_feature_routers(
    features_path: str = "features", router_var_name: str = "router"
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


    base_path = None

    

    features_path_fs = Path(*features_path.split("."))

    potential_path = get_path(features_path_fs)

    if potential_path.exists():
        base_path = potential_path

    if not base_path:
        message = (
            f"Error: No se pudo encontrar el directorio de features: {features_path}"
        )
        raise RuntimeError(message)

    # Buscar todos los archivos Python en el directorio features
    pattern = os.path.join(base_path, "**", "*.py")
    python_files = glob.glob(pattern, recursive=True)

    for file_path in python_files:
        filename = os.path.basename(file_path)

        # Ignorar __init__.py, tests, etc.
        if filename.startswith("__") or filename.startswith("test_"):
            continue

        try:

            rel_path = os.path.relpath(file_path, base_path)
            module_path_parts = rel_path.replace(os.sep, ".").split(".")[:-1]
            full_module_name = f"{features_path}.{'.'.join(module_path_parts)}"

            spec = importlib.util.spec_from_file_location(full_module_name, file_path)

            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[full_module_name] = module
                spec.loader.exec_module(module)
                if hasattr(module, router_var_name):
                    routers.append(getattr(module, router_var_name))

        except Exception as e:
            raise RuntimeError(f"✗ Error al importar {file_path}: {e}")

    return routers
