
from common.ioc import container
from common.server import get_feature_modules
from common.context import context
import uvicorn
from common.confg import Config,config
from common.context import context,Context
from common.openapi import setup_custom_openapi

from .custom_fastapi import CustomFastApi

class AppBuilder:
    """
    Clase para construir y ejecutar una aplicación FastAPI utilizando
    un patrón de diseño fluido ("fluent builder").
    """
    
    def __init__(self, config:Config=config(), context:Context = context):      
        
        self._host = "0.0.0.0"
        self._port = config.port        
        self._app= CustomFastApi(config=config,context=context)
    

    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI."""                
        
        
        routers, module_names = get_feature_modules(self._app.config.features)

        if not routers:
            print("⚠ Advertencia: No se encontraron routers en las features")
        
        if not module_names:
            print("⚠ Advertencia: No se encontraron módulos para inyección de dependencias")

        # Wire del container solo si hay módulos
        if module_names:
            print("Configurando inyección de dependencias...")
            try:                
                container.wire(modules=self._app.context.modules)
                print("✓ Inyección de dependencias configurada")
            except Exception as e:
                print(f"⚠ Error configurando inyección de dependencias: {e}")

        # Registrar routers
        print("Registrando routers...")
        for router in routers:
            try:
                self._app.include_router(router)                
            except Exception as e:
                raise e
        
        print(f"  - {len(routers)} routers registrados")
        print(f"  - {len(module_names)} módulos configurados para DI")
        
        setup_custom_openapi(self._app)

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:       
        
        self.build()

        # Usar los valores pasados como parámetros o los configurados en la clase
        final_host = host or self._host
        final_port = port or self._app.config.port
        
        print(f"🚀 Iniciando servidor en http://{final_host}:{final_port}")
        uvicorn.run(self._app, host=final_host, port=final_port)

    