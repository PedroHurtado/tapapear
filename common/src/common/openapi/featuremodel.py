from pydantic import BaseModel
from typing import ClassVar, Set

class FeatureModel(BaseModel):
    _ignore_parts: ClassVar[Set[str]] = {"commands", "queries", "models"}  # <- ClassVar
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        try:
            # Dividir módulo en partes
            module_parts = cls.__module__.split(".")

            # Quitar partes ignoradas
            filtered_parts = [p for p in module_parts if p not in cls._ignore_parts]

            # Buscar "features" y tomar lo que sigue
            if "features" in filtered_parts:
                start_idx = filtered_parts.index("features") + 1
            else:
                start_idx = 0

            relevant_parts = filtered_parts[start_idx:]

            # Función snake_case -> PascalCase
            def pascal_case(s: str) -> str:
                return "".join(word.capitalize() for word in s.split("_") if word)

            feature_name = "".join(pascal_case(p) for p in relevant_parts) or "Default"

            # Configurar título único
            cls.model_config = {"title": f"{feature_name}{cls.__name__}"}

        except Exception as e:
            cls.model_config = {"title": f"Unknown{cls.__name__}"}
            print(f"[FeatureModel] Error generando título para {cls.__name__}: {e}")