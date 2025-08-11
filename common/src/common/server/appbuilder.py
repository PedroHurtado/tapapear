import os
import importlib
from fastapi import FastAPI
from common.ioc.container import container
from common.server import get_feature_modules
import uvicorn


class AppBuilder:
    """
    Clase para construir y ejecutar una aplicación FastAPI utilizando
    un patrón de diseño fluido ("fluent builder").
    """
    def __init__(self):
        """
        Inicializa el AppBuilder sin parámetros.
        """
        self.title = None
        self.module_name = None
        self._app = None
    
    def with_title(self, title: str) -> "AppBuilder":
        """
        Configura el título de la aplicación.
        """
        self.title = title
        return self

    def with_module_name(self, module_name: str) -> "AppBuilder":
        """
        Configura el nombre del módulo base para resolver la ruta.
        """
        self.module_name = module_name
        return self

    
    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""
        if not self.title or not self.module_name:
            raise ValueError("Debes configurar el título y el nombre del módulo antes de construir la aplicación.")

        self._app = FastAPI(title=self.title)
        
        # Obtener la ruta base a partir del nombre del módulo
        
        
        # Cargar features dinámicamente usando la ruta base
        # Se asume que get_feature_modules acepta un argumento 'base_path'.
        routers, module_names = get_feature_modules(base_path=self.module_name)
        
        # Wire del container
        container.wire(modules=module_names)
        
        # Registrar routers
        for router in routers:
            self._app.include_router(router)
        
        return self
    
    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Ejecuta la aplicación (bloquea la ejecución)."""
        if not self._app:
            self.build()
        
        uvicorn.run(self._app, host=host, port=port)
    
    @property
    def app(self) -> FastAPI:
        """Getter para obtener la instancia de FastAPI sin ejecutar el servidor."""
        if not self._app:
            self.build()
        return self._app
