import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.endpoints import router
from core.config import Config
from core.database import MySQLConnection
from services.data_service import DataService
from services.recommendation import RecommendationEngine
from services.tracking import ActivityTracker
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

_flush_task: Optional[asyncio.Task] = None

# Singletons globales para compartir entre workers (con preload_app=True)
_data_service: Optional[DataService] = None
_recommendation_engine: Optional[RecommendationEngine] = None
_mysql_connection: Optional[MySQLConnection] = None


async def periodic_flush(tracker: ActivityTracker, interval_seconds: int) -> None:
    """
    Ejecuta flush periodico de actividades de Redis a MySQL.

    Args:
        tracker: Instancia de ActivityTracker para ejecutar flush
        interval_seconds: Intervalo en segundos entre cada flush
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            count = tracker.flush_all_pending_activities()
            logger.info(f"Flush automatico: {count} actividades transferidas")
        except Exception as e:
            logger.error(f"Error en flush automatico: {e}")


def initialize_services():
    """
    Inicializa servicios globales (DataService, RecommendationEngine).

    Ejecutado UNA vez con preload_app=True en Gunicorn.
    Compartido entre todos los workers.
    """
    global _data_service, _recommendation_engine, _mysql_connection

    if _data_service is not None:
        logger.info("Servicios ya inicializados (reutilizando)")
        return

    logger.info("Inicializando servicios globales...")

    try:
        # Inicializar DataService (maneja conexión y túnel SSH internamente)
        DataService._instancia = None
        _data_service = DataService(connection_factory=MySQLConnection)
        _data_service.load_all_data()
        logger.info(
            f"DataService inicializado: {len(_data_service.users_df)} users, "
            f"{len(_data_service.videos_df)} videos, "
            f"{len(_data_service.interactions_df)} interactions"
        )

        # Inicializar RecommendationEngine
        _recommendation_engine = RecommendationEngine(_data_service)
        logger.info("RecommendationEngine inicializado")

        logger.info("Todos los servicios inicializados exitosamente")

    except Exception as e:
        logger.error(f"Error inicializando servicios: {e}")
        raise


def get_data_service() -> DataService:
    """
    Obtiene instancia global de DataService.

    Returns:
        Instancia compartida de DataService
    """
    if _data_service is None:
        initialize_services()
    return _data_service


def get_recommendation_engine() -> RecommendationEngine:
    """
    Obtiene instancia global de RecommendationEngine.

    Returns:
        Instancia compartida de RecommendationEngine
    """
    if _recommendation_engine is None:
        initialize_services()
    return _recommendation_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Administra el ciclo de vida de la aplicacion FastAPI.

    Inicia servicios globales y tarea de flush periodico al arrancar.
    Limpia recursos al apagar.

    Args:
        app: Instancia de FastAPI

    Yields:
        None
    """
    global _flush_task

    config = Config()

    # Inicializar servicios globales
    logger.info("Iniciando FastAPI...")
    initialize_services()

    # Iniciar flush periodico
    tracker = ActivityTracker()
    logger.info("Iniciando flush automatico")
    _flush_task = asyncio.create_task(
        periodic_flush(tracker, config.FLUSH_INTERVAL_SECONDS)
    )

    logger.info("FastAPI listo para recibir requests")

    yield

    # Cleanup
    logger.info("Deteniendo FastAPI...")

    if _flush_task:
        _flush_task.cancel()
        logger.info("Flush task cancelada")

    # Cerrar connection pool
    try:
        MySQLConnection.close_pool()
        logger.info("Connection pool cerrado")
    except Exception as e:
        logger.error(f"Error cerrando connection pool: {e}")

    logger.info("FastAPI detenido")


def create_app() -> FastAPI:
    """
    Factory function para crear instancia de FastAPI.

    Returns:
        Instancia configurada de FastAPI
    """
    config = Config()

    app = FastAPI(
        title="TalentPitch Search API",
        description="Servicio de recomendaciones con bandits contextuales",
        version="2.0",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if config.API_PATH:
        logger.info(f"Incluyendo router con prefijo: {config.API_PATH}")
        app.include_router(router, prefix=config.API_PATH)
    else:
        logger.info("Incluyendo router con prefijo por defecto: /api")
        app.include_router(router, prefix="/api")

    @app.get("/")
    async def root():
        """
        Endpoint raiz que retorna informacion basica del API.

        Returns:
            Diccionario con mensaje, status y version
        """
        return {
            "message": "TalentPitch Search API",
            "status": "ok",
            "version": "2.0"
        }

    @app.get("/health")
    async def health():
        """
        Health check endpoint para Kubernetes liveness probe.

        Returns:
            Diccionario con status y version
        """
        return {"status": "healthy", "version": "2.0"}

    if config.API_PATH:
        @app.get(config.API_PATH)
        async def root_with_prefix():
            """
            Endpoint raiz con prefijo configurado.

            Returns:
                Diccionario con mensaje, status, version y path
            """
            return {
                "message": "TalentPitch Search API",
                "status": "ok",
                "version": "2.0",
                "path": config.API_PATH
            }

    return app


app = create_app()
