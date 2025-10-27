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

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.endpoints import router
app.include_router(router)

@app.get("/")
async def root():
    """
    Endpoint raiz que retorna informacion basica del API.
    """
    return {"message": "TalentPitch Search API", "status": "ok", "version": "2.0"}
