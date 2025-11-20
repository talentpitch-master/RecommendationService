import os
from pathlib import Path
from typing import Any, Optional

import redis
from dotenv import load_dotenv

from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class RedisConnection:
    """
    Conexion singleton a Redis.

    Utiliza patron singleton para mantener una sola instancia de conexion.
    """

    _instance: Optional['RedisConnection'] = None
    _initialized: bool = False

    def __new__(cls) -> 'RedisConnection':
        """
        Crea nueva instancia usando patron singleton.

        Returns:
            Instancia unica de RedisConnection
        """
        if cls._instance is None:
            cls._instance = super(RedisConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Inicializa conexion Redis.

        Solo se ejecuta una vez gracias al patron singleton.
        """
        if self._initialized:
            return

        self._initialized = True
        self.connection: Optional[redis.Redis] = None
        self._load_credentials()

    def _load_credentials(self) -> None:
        """
        Carga credenciales desde archivo .env.

        Raises:
            FileNotFoundError: Si no encuentra archivo .env
        """
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent
        env_path = project_root / '.env'

        if not env_path.exists():
            raise FileNotFoundError(
                f"No se encontro .env en la raiz del proyecto: {env_path}"
            )

        load_dotenv(env_path)

        self.redis_host = os.getenv('REDIS_HOST')
        self.redis_port = int(os.getenv('REDIS_PORT', '6379'))
        self.redis_password = os.getenv('REDIS_PASSWORD')
        self.redis_scheme = os.getenv('REDIS_SCHEME', 'redis')

    def connect(self) -> bool:
        """
        Establece conexion directa a Redis.

        Configura SSL segun REDIS_SCHEME y conecta a db=1.

        Returns:
            True si conexion exitosa

        Raises:
            ConnectionError: Si falla la conexion a Redis
        """
        use_ssl = self.redis_scheme == 'tls'

        logger.info(
            f"Conectando a Redis - Host: {self.redis_host}:{self.redis_port}, "
            f"SSL={use_ssl}, db=1"
        )

        try:
            self.connection = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
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
            raise ConnectionError(f"Error conectando a Redis: {e}")

    def close(self) -> None:
        """
        Cierra la conexion a Redis.
        """
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            finally:
                self.connection = None

    def __enter__(self) -> 'RedisConnection':
        """
        Soporte para context manager.

        Returns:
            Instancia de RedisConnection con conexion activa
        """
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[Exception],
        exc_tb: Optional[Any]
    ) -> bool:
        """
        Cierra conexion al salir del context manager.

        Args:
            exc_type: Tipo de excepcion si ocurrio
            exc_val: Valor de excepcion si ocurrio
            exc_tb: Traceback de excepcion si ocurrio

        Returns:
            False para propagar excepciones
        """
        self.close()
        return False
