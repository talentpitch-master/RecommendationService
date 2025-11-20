"""
Punto de entrada principal para el servidor de busqueda y recomendaciones.

Inicia servidor Uvicorn con configuracion desde Config singleton.
Solo para desarrollo - en produccion se usa Gunicorn.
"""
import uvicorn

from api.server import app
from core.config import Config
from utils.logger import LoggerConfig


if __name__ == "__main__":
    logger = LoggerConfig.get_logger(__name__)
    config = Config()

    logger.info(f"Starting server on port {config.API_PORT}")

    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        reload=config.DEBUG,
        log_level="info",
        limit_concurrency=config.UVICORN_LIMIT_CONCURRENCY,
        limit_max_requests=config.UVICORN_LIMIT_MAX_REQUESTS,
        timeout_keep_alive=config.UVICORN_TIMEOUT_KEEP_ALIVE,
        timeout_graceful_shutdown=config.UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN,
        proxy_headers=True,
        forwarded_allow_ips=config.UVICORN_FORWARDED_ALLOW_IPS
    ) 