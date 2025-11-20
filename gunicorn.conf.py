"""
Configuracion de Gunicorn para produccion.

Configuracion optimizada para throughput alto, connection pooling MySQL,
preload app y timeouts apropiados para recomendaciones.
"""

import multiprocessing
import os
from typing import Any


bind: str = os.getenv('GUNICORN_BIND', '0.0.0.0:5005')

workers: int = int(os.getenv('GUNICORN_WORKERS', str(multiprocessing.cpu_count() * 2)))
worker_class: str = 'uvicorn.workers.UvicornWorker'
worker_connections: int = int(os.getenv('GUNICORN_WORKER_CONNECTIONS', '1000'))

max_requests: int = int(os.getenv('GUNICORN_MAX_REQUESTS', '5000'))
max_requests_jitter: int = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '500'))
timeout: int = int(os.getenv('GUNICORN_TIMEOUT', '120'))
graceful_timeout: int = int(os.getenv('GUNICORN_GRACEFUL_TIMEOUT', '30'))
keepalive: int = int(os.getenv('GUNICORN_KEEPALIVE', '65'))

preload_app: bool = os.getenv('GUNICORN_PRELOAD_APP', 'True').lower() == 'true'

accesslog: str = os.getenv('GUNICORN_ACCESS_LOG', '-')
errorlog: str = os.getenv('GUNICORN_ERROR_LOG', '-')
loglevel: str = os.getenv('GUNICORN_LOG_LEVEL', 'info')
access_log_format: str = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

proc_name: str = os.getenv('GUNICORN_PROC_NAME', 'recommendation_service')

forwarded_allow_ips: str = os.getenv('GUNICORN_FORWARDED_ALLOW_IPS', '*')
proxy_protocol: bool = os.getenv('GUNICORN_PROXY_PROTOCOL', 'False').lower() == 'true'
proxy_allow_ips: str = os.getenv('GUNICORN_PROXY_ALLOW_IPS', '*')


def on_starting(server: Any) -> None:
    """
    Hook ejecutado cuando Gunicorn inicia.

    Args:
        server: Instancia del servidor Gunicorn
    """
    print(f"Iniciando Gunicorn con {workers} workers")
    print(f"Preload app: {preload_app}")
    print(f"Binding: {bind}")


def when_ready(server: Any) -> None:
    """
    Hook ejecutado cuando servidor esta listo.

    Args:
        server: Instancia del servidor Gunicorn
    """
    print("Servidor listo para recibir requests")


def on_exit(server: Any) -> None:
    """
    Hook ejecutado en shutdown.

    Args:
        server: Instancia del servidor Gunicorn
    """
    print("Cerrando servidor...")

    try:
        from core.database import MySQLConnection
        MySQLConnection.close_pool()
        print("Connection pool cerrado")
    except Exception as e:
        print(f"Error cerrando connection pool: {e}")


def worker_int(worker: Any) -> None:
    """
    Hook ejecutado cuando worker recibe SIGINT/SIGTERM.

    Args:
        worker: Instancia del worker
    """
    print(f"Worker {worker.pid} recibio señal de cierre")
