import os
import time
import redis
from pathlib import Path
from sshtunnel import SSHTunnelForwarder
from dotenv import load_dotenv
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

class RedisConnection:
    """
    Conexion singleton a Redis con tunel SSH.
    Utiliza patron singleton para mantener una sola instancia de la conexion.
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RedisConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if RedisConnection._initialized:
            return

        RedisConnection._initialized = True
        self.tunnel = None
        self.connection = None
        self._load_credentials()

    def _load_credentials(self):
        """
        Carga credenciales desde archivo .env en carpeta credentials.
        Configura variables para SSH y Redis.
        """
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent
        env_path = project_root / 'credentials' / '.env'

        if not env_path.exists():
            raise FileNotFoundError(f"No se encontro .env en: {env_path}")

        load_dotenv(env_path)

        self.ssh_key_path = project_root / 'credentials' / 'talethpitch-develop-bastion.pem'
        if not self.ssh_key_path.exists():
            raise FileNotFoundError(f"No se encontro clave SSH en: {self.ssh_key_path}")

        self.ssh_host = os.getenv('SSH_HOST')
        self.ssh_user = os.getenv('SSH_USER')
        self.redis_host = os.getenv('REDIS_HOST')
        self.redis_port = int(os.getenv('REDIS_PORT'))
        self.redis_password = os.getenv('REDIS_PASSWORD')
        self.redis_scheme = os.getenv('REDIS_SCHEME')

    def connect(self):
        """
        Establece tunel SSH y conexion a Redis.
        Configura SSL segun REDIS_SCHEME y conecta a db=1.
        """
        logger.info("Estableciendo tunel SSH para Redis")
        try:
            self.tunnel = SSHTunnelForwarder(
                (self.ssh_host, 22),
                ssh_username=self.ssh_user,
                ssh_pkey=str(self.ssh_key_path),
                remote_bind_address=(self.redis_host, self.redis_port),
                local_bind_address=('127.0.0.1', 0)
            )
            self.tunnel.start()
            logger.info(f"Tunel establecido en puerto local {self.tunnel.local_bind_port}")
            time.sleep(1)
        except Exception as e:
            raise ConnectionError(f"Error estableciendo tunel SSH: {e}")

        use_ssl = self.redis_scheme == 'tls'

        logger.info(f"Conectando a Redis con SSL={use_ssl}, db=1")
        try:
            self.connection = redis.Redis(
                host='127.0.0.1',
                port=self.tunnel.local_bind_port,
                db=1,
                password=self.redis_password if self.redis_password else None,
                decode_responses=True,
                ssl=use_ssl,
                ssl_cert_reqs=None if use_ssl else None,
                socket_connect_timeout=10,
                socket_timeout=10
            )
            response = self.connection.ping()
            logger.info(f"Redis PING exitoso: {response}")
            return True
        except Exception as e:
            if self.tunnel:
                self.tunnel.stop()
            raise ConnectionError(f"Error conectando a Redis: {e}")

    def close(self):
        """
        Cierra la conexion a Redis y el tunel SSH.
        """
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            finally:
                self.connection = None

        if self.tunnel:
            try:
                self.tunnel.stop()
            except:
                pass
            finally:
                self.tunnel = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
