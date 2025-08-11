from fastapy import FastApy
from common.ioc.container import container
from common.server import get_feature_modules
import uvicorn


class AppBuilder:
    def __init__(self, title: str):
        self.title = title
        self._app = None
    
    def build(self) -> "AppBuilder":
        """Construye la aplicación FastAPI"""
        self._app = FastAPI(title=self.title)
        
        # Cargar features dinámicamente
        routers, module_names = get_feature_modules()
        
        # Wire del container
        container.wire(modules=module_names)
        
        # Registrar routers
        for router in routers:
            self._app.include_router(router)
        
        return self
    
    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Ejecuta la aplicación (bloquea la ejecución)"""
        if not self._app:
            self.build()
        
        uvicorn.run(self._app, host=host, port=port)
    
    @property
    def app(self) -> FastAPI:
        """Getter para obtener la instancia de FastAPI sin ejecutar el servidor"""
        if not self._app:
            self.build()
        return self._app