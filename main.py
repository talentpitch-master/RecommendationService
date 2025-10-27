"""
Punto de entrada principal para el servidor de busqueda y recomendaciones.
Inicia servidor Uvicorn con configuracion desde Config singleton.
Solo para desarrollo - en produccion se usa Gunicorn.
"""
import os
import uvicorn
from core.config import Config

# Importar app desde api.server para poder ejecutar como modulo
from api.server import app

if __name__ == "__main__":
    import uvicorn
    config = Config()
    print(f"Starting server on port {config.API_PORT}...")
    uvicorn.run(
        app, 
        host=config.API_HOST, 
        port=config.API_PORT,
        reload=config.DEBUG,
        log_level="info",
        limit_concurrency=5,
        limit_max_requests=1000,
        timeout_keep_alive=65,
        timeout_graceful_shutdown=1800,
        proxy_headers=True,
        forwarded_allow_ips="*"
    ) 