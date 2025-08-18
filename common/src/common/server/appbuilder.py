from fastapi import FastAPI
from common.ioc import container
from common.server import get_feature_modules
from common.context import context
import uvicorn
from typing import Optional

class AppBuilder:
    """
    Clase para construir y ejecutar una aplicación FastAPI utilizando
    un patrón de diseño fluido ("fluent builder").
    """
    
    def __init__(self):
        """
        Inicializa el AppBuilder sin parámetros.
        """
        self.app_title = None
        self.features_path = "features"
        self._app = None
        self.host = "0.0.0.0"
        self.port = 8000

    def title(self, title: str) -> "AppBuilder":
        """
        Configura el título de la aplicación.
        """
        self.app_title = title
        return self

    def features(self, features_path: Optional[str]) -> "AppBuilder":
        if features_path is not None:
            self.features_path = features_path
        return self
    
    def host(self, host: Optional[str]) -> "AppBuilder":
        if host is not None:
            self.host = host
        return self
    
    def port(self, port: Optional[int]) -> "AppBuilder":
        if port is not None:
            self.port = port
        return self

    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""
        if not self.app_title or not self.features_path:
            raise ValueError(
                "Debes configurar el título y la ruta de features antes de construir la aplicación."
            )

        print(f"Construyendo aplicación: {self.app_title}")
        print(f"Features path: {self.features_path}")
        
        self._app = FastAPI(title=self.app_title)
        
        # Cargar features dinámicamente usando la ruta especificada
        routers, module_names = get_feature_modules(features_path=self.features_path)

        if not routers:
            print("⚠ Advertencia: No se encontraron routers en las features")
        
        if not module_names:
            print("⚠ Advertencia: No se encontraron módulos para inyección de dependencias")

        # Wire del container solo si hay módulos
        if module_names:
            print("Configurando inyección de dependencias...")
            try:                
                container.wire(modules=module_names)
                print("✓ Inyección de dependencias configurada")
            except Exception as e:
                print(f"⚠ Error configurando inyección de dependencias: {e}")

        # Registrar routers
        print("Registrando routers...")
        for i, router in enumerate(routers):
            try:
                self._app.include_router(router)
                print(f"✓ Router {i+1} registrado")
            except Exception as e:
                print(f"✗ Error registrando router {i+1}: {e}")

        print(f"✓ Aplicación '{self.app_title}' construida exitosamente")
        print(f"  - {len(routers)} routers registrados")
        print(f"  - {len(module_names)} módulos configurados para DI")
        
        return self

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Ejecuta la aplicación (bloquea la ejecución)."""
        if not self._app:
            self.build()

        # Usar los valores pasados como parámetros o los configurados en la clase
        final_host = host or self.host
        final_port = port or self.port
        
        print(f"🚀 Iniciando servidor en http://{final_host}:{final_port}")
        uvicorn.run(self._app, host=final_host, port=final_port)

    @property
    def app(self) -> FastAPI:
        """Getter para obtener la instancia de FastAPI sin ejecutar el servidor."""
        if not self._app:
            self.build()
        return self._app