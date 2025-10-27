import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

class Config:
    """
    Configuracion centralizada singleton para la aplicacion.
    Carga todas las variables de entorno y configuraciones de paths.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Inicializa configuracion cargando variables de entorno.
        Solo se ejecuta una vez gracias al patron singleton.
        """
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        print(os.getenv('MYSQL_HOST'))

        self.PROJECT_ROOT = Path(__file__).resolve().parent.parent
        self.DATA_DIR = self.PROJECT_ROOT / 'data'
        self.LOGS_DIR = self.PROJECT_ROOT / 'logs'

        self.MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
        self.MYSQL_PORT = int(os.getenv('MYSQL_PORT', 3306))
        self.MYSQL_USER = os.getenv('MYSQL_USER', 'root')
        self.MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
        self.MYSQL_DATABASE = os.getenv('MYSQL_DB', 'talent')

        self.REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
        self.REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
        self.REDIS_DB = int(os.getenv('REDIS_DB', 1))
        self.REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)
        self.REDIS_SCHEME = os.getenv('REDIS_SCHEME', 'redis')

        self.API_HOST = os.getenv('API_HOST', '0.0.0.0')
        self.API_PORT = int(os.getenv('API_PORT', 5005))
        self.DEBUG = os.getenv('FLASK_ENV', 'production') == 'development'

        self.FLUSH_INTERVAL_SECONDS = int(os.getenv('FLUSH_INTERVAL_SECONDS', 900))
        self.FLUSH_THRESHOLD_ACTIVITIES = int(os.getenv('FLUSH_THRESHOLD_ACTIVITIES', 50))

        self.BLACKLIST_FILE = self.DATA_DIR / 'blacklist.csv'
