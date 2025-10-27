"""
Punto de entrada principal para el servidor de busqueda y recomendaciones.
Inicia servidor Uvicorn con configuracion desde Config singleton.
Solo para desarrollo - en produccion se usa Gunicorn.
"""
import os
import uvicorn
from core.config import Config

if __name__ == '__main__':
    config = Config()

    uvicorn.run(
        "api.server:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG,
        log_level="info"
    )
