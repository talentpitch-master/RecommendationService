from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
from utils.logger import LoggerConfig
from services.tracking import ActivityTracker

logger = LoggerConfig.get_logger(__name__)

_flush_task = None

async def periodic_flush():
    """
    Ejecuta flush periodico de actividades de Redis a MySQL cada 15 minutos.
    Se ejecuta como tarea en background durante el ciclo de vida de FastAPI.
    """
    while True:
        try:
            await asyncio.sleep(900)
            tracker = ActivityTracker()
            count = tracker.flush_all_pending_activities()
            logger.info(f"Flush automatico: {count} actividades transferidas")
        except Exception as e:
            logger.error(f"Error en flush automatico: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Administra el ciclo de vida de la aplicacion FastAPI.
    Inicia la tarea de flush periodico al arrancar y la cancela al apagar.
    """
    global _flush_task
    logger.info("Iniciando FastAPI con flush automatico")
    _flush_task = asyncio.create_task(periodic_flush())
    yield
    if _flush_task:
        _flush_task.cancel()
    logger.info("FastAPI detenido")

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

from api.endpoints import router
from core.config import Config

config = Config()

# Incluir router con el prefijo configurado
# Si hay API_PATH (produccion): usa el prefijo directo
# Si no hay API_PATH (desarrollo local): agrega /api/ para mantener compatibilidad
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
    """
    return {"message": "TalentPitch Search API", "status": "ok", "version": "2.0"}

# Endpoint health check sin prefijo para Kubernetes
@app.get("/health")
async def health():
    """
    Health check endpoint sin prefijo para Kubernetes liveness probe.
    """
    return {"status": "healthy", "version": "2.0"}

# Si hay API_PATH, agregar endpoint raiz con el prefijo DESPUES de definir las rutas
if config.API_PATH:
    @app.get(config.API_PATH)
    async def root_with_prefix():
        """
        Endpoint raiz con prefijo - acepta GET para compatibilidad con navegadores.
        """
        return {"message": "TalentPitch Search API", "status": "ok", "version": "2.0", "path": config.API_PATH}
