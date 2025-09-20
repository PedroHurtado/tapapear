from typing import ClassVar, Set
from pydantic import BaseModel, model_serializer, SerializerFunctionWrapHandler


class FeatureModel(BaseModel):
    _ignore_parts: ClassVar[Set[str]] = {"commands", "queries", "models"}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        module_parts = cls.__module__.split(".")
        filtered_parts = [p for p in module_parts if p not in cls._ignore_parts]

        if "features" in filtered_parts:
            start_idx = filtered_parts.index("features") + 1
        else:
            start_idx = 0

        relevant_parts = filtered_parts[start_idx:]

        def pascal_case(s: str) -> str:
            return "".join(word.capitalize() for word in s.split("_") if word)

        feature_name = "".join(pascal_case(p) for p in relevant_parts if p)

        # Nombre bonito
        pretty_name = f"{feature_name}{cls.__name__}"

        # Lo ponemos en Pydantic (para schemas globales)
        cls.model_config = {"title": pretty_name, "arbitrary_types_allowed": True}

        # ⚡ Y además reasignamos __name__ para FastAPI
        cls.__name__ = pretty_name

    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
        if not isinstance(data, dict):
            return data

        # Filtrar valores None
        filtered_data = {k: v for k, v in data.items() if v is not None}
        return filtered_data
