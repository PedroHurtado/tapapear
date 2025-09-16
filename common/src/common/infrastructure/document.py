from uuid import UUID
from typing import Any, Annotated, get_args, get_origin

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    FieldSerializationInfo,
    ConfigDict,
    model_serializer,
    SerializerFunctionWrapHandler,
    SerializationInfo
    
    
)
from pydantic.fields import FieldInfo
from pydantic_core.core_schema import FieldValidationInfo
from common.inflect import plural

def id():
    return Field(metadata={"id": True})


def reference(collection_name: str = None):
    return Field(metadata={"reference": True, "collection_name": collection_name})


def collection(collection_name: str = None):
    return Field(metadata={"subcollection": collection_name})



class DocumentReference(BaseModel):
    path: str
    model_config = ConfigDict(frozen=True)
    
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info:SerializationInfo):
        data = serializer(self)        
        
        if info.mode == 'json':            
            return data
        else:        
            return DocumentReference(**data)

class CollectionReference(BaseModel):
    path: str
    model_config = ConfigDict(frozen=True)
    
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler, info:SerializationInfo):
        data = serializer(self)        
        
        if info.mode == 'json':            
            return data
        else:        
            return CollectionReference(**data)


class MixinSerializer(BaseModel):
    @model_serializer(mode="wrap")
    def __serialize_model(self, serializer: SerializerFunctionWrapHandler):
        data = serializer(self)
        return {k: v for k, v in data.items() if v is not None}

    @field_serializer("*")
    def __serialize_references(self, value: Any, info: FieldSerializationInfo) -> Any:
        model_fields = self.__class__.model_fields
        field_info = model_fields.get(info.field_name)
        
        if field_info:
            metadata = self.__get_custom_metadata(field_info)

            if metadata.get("id") is True:
                # Solo poner a None si es el documento raíz
                is_root = info.context and info.context.get("is_root", False)
                if is_root:
                    return None
                
                # Si tenemos un firestore_path en el contexto, crear CollectionReference
                firestore_path = info.context.get("firestore_path") if info.context else None
                if firestore_path:
                    return CollectionReference(path=firestore_path)
                
                # Para documentos anidados sin path específico, devolver el valor normal
                return str(value) if isinstance(value, UUID) else value

            if metadata.get("reference") is True:
                if value is not None:
                    return self.__get_document(value, metadata)
            
            # Manejar subcollections
            if "subcollection" in metadata:
                if value is not None:
                    # Pasar el contexto del path padre si existe
                    parent_path = info.context.get("parent_path") if info.context else None
                    return self.__serialize_subcollection(value, info.field_name, metadata, parent_path)

        return value

    def __serialize_subcollection(self, value, field_name: str, metadata: dict, parent_path: str = None):
        """Serializa una subcollection manejando el anidamiento automático"""
        # Determinar el nombre/expresión de la collection
        collection_expression = metadata.get("subcollection")
        if collection_expression is None:
            # Usar el nombre del campo como nombre de la collection
            collection_expression = plural(field_name)  # ✅ pluralizado

        # Construir el path base para esta subcollection
        base_path = self.__build_collection_path(collection_expression, parent_path)
        
        if isinstance(value, list):
            return [self.__serialize_subcollection_item(item, base_path) for item in value]
        else:
            return self.__serialize_subcollection_item(value, base_path)

    def __serialize_subcollection_item(self, item, base_path: str):
        """Serializa un item individual de una subcollection"""
        if not hasattr(item, 'model_dump'):
            return item
        
        # Si el item tiene un id, construir la ruta completa con el id del documento
        item_id = getattr(item, 'id', None)
        context = {"parent_path": base_path}
        
        if item_id is not None:
            item_id_str = str(item_id) if isinstance(item_id, UUID) else item_id
            full_path = f"{base_path}/{item_id_str}"
            # Pasar el firestore_path en el contexto para que se use como id
            context.update({
                "parent_path": full_path,
                "firestore_path": full_path
            })

        # Serializar el item con el contexto
        serialized = item.model_dump(context=context)
        
        return serialized

    def __build_collection_path(self, collection_expression: str, parent_path: str = None) -> str:
        """Construye el path completo para una subcollection usando expresiones"""
        import re
        
        # Buscar expresiones del tipo {attribute_name}
        pattern = r'\{([^}]+)\}'
        matches = re.finditer(pattern, collection_expression)
        
        resolved_expression = collection_expression
        
        for match in matches:
            attribute_name = match.group(1)
            placeholder = match.group(0)  # {attribute_name}
            
            # Buscar el valor del atributo en la instancia actual
            attribute_value = self.__get_attribute_value(attribute_name)
            
            if attribute_value is not None:
                # Reemplazar el placeholder con el valor real
                resolved_expression = resolved_expression.replace(placeholder, str(attribute_value))
            else:
                # Si no se encuentra el atributo, mantener el placeholder
                pass
        
        # Si tenemos un parent_path del contexto, usarlo; sino obtener el path actual
        if parent_path:
            base_path = parent_path
        else:
            base_path = self.__get_current_document_path()
        
        if base_path:
            return f"{base_path}/{resolved_expression}"
        else:
            return resolved_expression

    def __get_current_document_path(self) -> str:
        """Obtiene el path del documento actual"""
        class_name = plural(self.__class__.__name__.lower())  # ✅ pluralizado
        
        # Buscar el campo id en este documento
        doc_id = None
        for field_name, field_info in self.__class__.model_fields.items():
            metadata = self.__get_custom_metadata(field_info)
            if metadata.get("id") is True:
                doc_id = getattr(self, field_name, None)
                break
        
        if doc_id is not None:
            doc_id_str = str(doc_id) if isinstance(doc_id, UUID) else doc_id
            return f"{class_name}/{doc_id_str}"
        
        # Si no tiene id, solo devolver el nombre de la clase
        return class_name

    def __get_attribute_value(self, attribute_name: str):
        """Obtiene el valor de un atributo de la instancia actual"""
        try:
            return getattr(self, attribute_name, None)
        except:
            return None   

    def __get_custom_metadata(self, field_info: FieldInfo) -> dict:
        metadata = self.__get_metadata_from(field_info)
        if metadata:
            return metadata

        default = getattr(field_info, "default", None)
        if get_origin(default) is Annotated:
            for arg in get_args(default):
                if isinstance(arg, FieldInfo):
                    metadata = self.__get_metadata_from(arg)
                    if metadata:
                        return metadata

        return {}

    def __get_metadata_from(self, obj: Any) -> dict:
        schema_extra = getattr(obj, "json_schema_extra", None)
        if schema_extra:
            return schema_extra.get("metadata", {})
        return {}

    def __get_document(self, value, metadata):
        if not isinstance(value, Document):
            raise ValueError(
                f"El valor de referencia debe ser una instancia de Document, recibido: {type(value)}"
            )

        collection_name = (
            metadata.get("collection_name") or plural(value.__class__.__name__.lower())  # ✅ pluralizado
        )
        doc_id = str(value.id) if isinstance(value.id, UUID) else value.id
        return DocumentReference(path=f"{collection_name}/{doc_id}")

    model_config = ConfigDict(frozen=True)





class Document(MixinSerializer):
    id: UUID = id()

    def __eq__(self, value):
        return isinstance(value, Document) and value.id == self.id

    def __hash__(self):
        return hash(self.id)


class Embeddable(MixinSerializer): ...
