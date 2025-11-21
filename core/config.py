import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class Config:
    """
    Configuracion centralizada de la aplicacion.

    Carga variables de entorno y configuraciones de paths.
    Implementa patron singleton para garantizar una unica instancia.
    """

    _instance: Optional['Config'] = None
    _initialized: bool = False

    def __new__(cls) -> 'Config':
        """
        Crea nueva instancia usando patron singleton.

        Returns:
            Instancia unica de Config
        """
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Inicializa configuracion cargando variables de entorno.

        Solo se ejecuta una vez gracias al patron singleton.
        """
        if self._initialized:
            return

        self._initialized = True
        self._load_environment()
        self._setup_paths()
        self._load_mysql_config()
        self._load_redis_config()
        self._load_api_config()
        self._load_flush_config()
        self._load_uvicorn_config()
        self._setup_data_paths()
        self._log_configuration()

    def _load_environment(self) -> None:
        """
        Carga variables de entorno desde archivo .env.

        Raises:
            FileNotFoundError: Si no encuentra archivo .env
        """
        env_path = Path(__file__).resolve().parent.parent / 'credentials' / '.env'

        if not env_path.exists():
            raise FileNotFoundError(
                f"Archivo .env no encontrado en: {env_path}"
            )

        load_dotenv(dotenv_path=env_path)

    def _setup_paths(self) -> None:
        """
        Configura paths del proyecto.
        """
        self.PROJECT_ROOT = Path(__file__).resolve().parent.parent
        self.DATA_DIR = self.PROJECT_ROOT / 'data'
        self.LOGS_DIR = self.PROJECT_ROOT / 'logs'

    def _load_mysql_config(self) -> None:
        """
        Carga configuracion de MySQL desde variables de entorno.

        Raises:
            ValueError: Si faltan variables requeridas
        """
        self.MYSQL_HOST = self._get_required_env('MYSQL_HOST')
        self.MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
        self.MYSQL_USER = self._get_required_env('MYSQL_USER')
        self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
        self.MYSQL_DATABASE = self._get_required_env('MYSQL_DB')

    def _load_redis_config(self) -> None:
        """
        Carga configuracion de Redis desde variables de entorno.

        Raises:
            ValueError: Si faltan variables requeridas
        """
        self.REDIS_HOST = self._get_required_env('REDIS_HOST')
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', '6379'))
        self.REDIS_DB = int(os.getenv('REDIS_DB', '1'))
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
        self.REDIS_SCHEME = os.getenv('REDIS_SCHEME', 'redis')

    def _load_api_config(self) -> None:
        """
        Carga configuracion del API desde variables de entorno.
        """
        self.API_HOST = os.getenv('API_HOST', '0.0.0.0')
        self.API_PORT = int(os.getenv('API_PORT', '5005'))
        self.API_PATH = os.getenv('API_PATH', '')
        self.DEBUG = os.getenv('FLASK_ENV', 'production') == 'development'

    def _load_flush_config(self) -> None:
        """
        Carga configuracion de flush de actividades desde variables de entorno.
        """
        self.FLUSH_INTERVAL_SECONDS = int(
            os.getenv('FLUSH_INTERVAL_SECONDS', '900')
        )
        self.FLUSH_THRESHOLD_ACTIVITIES = int(
            os.getenv('FLUSH_THRESHOLD_ACTIVITIES', '50')
        )
        self.ACTIVITY_TTL_SECONDS = int(
            os.getenv('ACTIVITY_TTL_SECONDS', '86400')
        )
        self.SESSION_TTL_SECONDS = int(
            os.getenv('SESSION_TTL_SECONDS', '3600')
        )

    def _load_uvicorn_config(self) -> None:
        """
        Carga configuracion de Uvicorn desde variables de entorno.
        """
        self.UVICORN_LIMIT_CONCURRENCY = int(
            os.getenv('UVICORN_LIMIT_CONCURRENCY', '5')
        )
        self.UVICORN_LIMIT_MAX_REQUESTS = int(
            os.getenv('UVICORN_LIMIT_MAX_REQUESTS', '1000')
        )
        self.UVICORN_TIMEOUT_KEEP_ALIVE = int(
            os.getenv('UVICORN_TIMEOUT_KEEP_ALIVE', '65')
        )
        self.UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN = int(
            os.getenv('UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN', '1800')
        )
        self.UVICORN_FORWARDED_ALLOW_IPS = os.getenv(
            'UVICORN_FORWARDED_ALLOW_IPS', '*'
        )

    def _setup_data_paths(self) -> None:
        """
        Configura paths de archivos de datos.
        """
        self.BLACKLIST_FILE = self.DATA_DIR / 'blacklist.csv'

    def _log_configuration(self) -> None:
        """
        Registra configuracion actual en logs.
        """
        if self.API_PATH:
            print(f"API_PATH configurado: '{self.API_PATH}'")
            print(
                f"Rutas disponibles en: "
                f"http://{self.API_HOST}:{self.API_PORT}"
                f"{self.API_PATH}/search/..."
            )
        else:
            print("API_PATH no configurado (usando prefijo /api por defecto)")
            print(
                f"Rutas disponibles en: "
                f"http://{self.API_HOST}:{self.API_PORT}/api/search/..."
            )

    @staticmethod
    def _get_required_env(key: str) -> str:
        """
        Obtiene variable de entorno requerida.

        Args:
            key: Nombre de la variable de entorno

        Returns:
            Valor de la variable de entorno

        Raises:
            ValueError: Si la variable no existe o esta vacia
        """
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"Variable de entorno requerida no encontrada: {key}"
            )
        return value
