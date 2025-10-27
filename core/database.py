import os
import pymysql
from pathlib import Path
from sshtunnel import SSHTunnelForwarder
from dotenv import load_dotenv
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

class MySQLConnection:
    """
    Conexion singleton a MySQL con tunel SSH.
    Utiliza patron singleton para mantener una sola instancia de la conexion.
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MySQLConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if MySQLConnection._initialized:
            return

        MySQLConnection._initialized = True
        self.tunnel = None
        self.connection = None
        self._load_credentials()

    def _load_credentials(self):
        """
        Carga credenciales desde archivo .env en carpeta credentials.
        Configura path de clave SSH para el tunel.
        """
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent

        env_path = project_root / 'credentials' / '.env'
        if not env_path.exists():
            raise FileNotFoundError(f"No se encontro .env en: {env_path}")

        load_dotenv(env_path)
        logger.info(f"Credenciales cargadas desde: {env_path}")

        self.ssh_key_path = project_root / 'credentials' / 'talethpitch-develop-bastion.pem'
        if not self.ssh_key_path.exists():
            raise FileNotFoundError(f"No se encontro clave SSH en: {self.ssh_key_path}")

    def connect(self):
        """
        Establece tunel SSH y conexion a MySQL.
        Valida variables requeridas y configura cursores tipo DictCursor.
        """
        environment = os.getenv('ENVIRONMENT', 'staging').lower()
        prefix = 'PROD' if environment == 'prod' else 'STG'

        ssh_host = os.getenv('SSH_HOST')
        ssh_user = os.getenv('SSH_USER')
        mysql_host = os.getenv(f'{prefix}_MYSQL_HOST')
        mysql_user = os.getenv(f'{prefix}_MYSQL_USER')
        mysql_password = os.getenv(f'{prefix}_MYSQL_PASSWORD')
        mysql_db = os.getenv(f'{prefix}_MYSQL_DB')
        mysql_port = int(os.getenv(f'{prefix}_MYSQL_PORT', '3306'))

        required_vars = {
            'SSH_HOST': ssh_host,
            'SSH_USER': ssh_user,
            f'{prefix}_MYSQL_HOST': mysql_host,
            f'{prefix}_MYSQL_USER': mysql_user,
            f'{prefix}_MYSQL_DB': mysql_db
        }

        missing = [k for k, v in required_vars.items() if not v]
        if missing:
            raise ValueError(f"Variables de entorno faltantes: {', '.join(missing)}")

        logger.info(f"Iniciando tunel SSH hacia {ssh_user}@{ssh_host}")

        try:
            self.tunnel = SSHTunnelForwarder(
                (ssh_host, 22),
                ssh_username=ssh_user,
                ssh_pkey=str(self.ssh_key_path),
                remote_bind_address=(mysql_host, mysql_port),
                local_bind_address=('127.0.0.1', 0)
            )
            self.tunnel.start()
            logger.info(f"Tunel SSH establecido en puerto local {self.tunnel.local_bind_port}")
        except Exception as e:
            logger.error(f"Error estableciendo tunel SSH: {e}")
            raise

        logger.info(f"Conectando a MySQL - DB: {mysql_db}")

        try:
            self.connection = pymysql.connect(
                host="127.0.0.1",
                port=self.tunnel.local_bind_port,
                user=mysql_user,
                password=mysql_password,
                db=mysql_db,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=30,
                read_timeout=60,
                write_timeout=60
            )
            logger.info("Conexion MySQL establecida exitosamente")
            return self.connection
        except Exception as e:
            logger.error(f"Error conectando a MySQL: {e}")
            if self.tunnel:
                self.tunnel.stop()
            raise

    def execute_query(self, query, params=None):
        """
        Ejecuta query SQL en MySQL.
        Retorna resultados para SELECT o numero de filas afectadas para INSERT/UPDATE/DELETE.
        """
        if not self.connection:
            raise RuntimeError("No hay conexion establecida. Llama a connect() primero.")

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params or ())

                query_type = query.strip().upper().split()[0]

                if query_type in ('SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN'):
                    results = cursor.fetchall()
                    logger.debug(f"Query SELECT ejecutada: {len(results)} filas obtenidas")
                    return results
                else:
                    self.connection.commit()
                    affected = cursor.rowcount
                    logger.debug(f"Query {query_type} ejecutada: {affected} filas afectadas")
                    return affected
        except Exception as e:
            logger.error(f"Error ejecutando query: {e}")
            logger.debug(f"Query: {query[:200]}...")
            raise

    def close(self):
        """
        Cierra la conexion a MySQL y el tunel SSH.
        """
        if self.connection:
            try:
                self.connection.close()
                logger.info("Conexion MySQL cerrada")
            except Exception as e:
                logger.error(f"Error cerrando conexion MySQL: {e}")
            finally:
                self.connection = None

        if self.tunnel:
            try:
                self.tunnel.stop()
                logger.info("Tunel SSH cerrado")
            except Exception as e:
                logger.error(f"Error cerrando tunel SSH: {e}")
            finally:
                self.tunnel = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
