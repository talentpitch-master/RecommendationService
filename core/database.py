import os
import pymysql
from pathlib import Path
from dotenv import load_dotenv
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

class MySQLConnection:
    """
    Conexion singleton a MySQL.
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
        self.connection = None
        self._load_credentials()

    def _load_credentials(self):
        """
        Carga credenciales desde archivo .env en la raiz del proyecto.
        """
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent

        env_path = project_root / '.env'
        
        if not env_path.exists():
            raise FileNotFoundError(f"No se encontro .env en la raiz del proyecto: {env_path}")

        load_dotenv(env_path)
        logger.info(f"Credenciales cargadas desde: {env_path}")

    def connect(self):
        """
        Establece conexion directa a MySQL.
        Valida variables requeridas y configura cursores tipo DictCursor.
        """
        mysql_host = os.getenv('MYSQL_HOST')
        mysql_port = int(os.getenv('MYSQL_PORT', '3306'))
        mysql_user = os.getenv('MYSQL_USER')
        mysql_password = os.getenv('MYSQL_PASSWORD')
        mysql_db = os.getenv('MYSQL_DB')

        required_vars = {
            'MYSQL_HOST': mysql_host,
            'MYSQL_USER': mysql_user,
            'MYSQL_DB': mysql_db
        }

        missing = [k for k, v in required_vars.items() if not v]
        if missing:
            raise ValueError(f"Variables de entorno faltantes: {', '.join(missing)}")

        logger.info(f"Conectando a MySQL - Host: {mysql_host}:{mysql_port}, DB: {mysql_db}")

        try:
            self.connection = pymysql.connect(
                host=mysql_host,
                port=mysql_port,
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
        Cierra la conexion a MySQL.
        """
        if self.connection:
            try:
                self.connection.close()
                logger.info("Conexion MySQL cerrada")
            except Exception as e:
                logger.error(f"Error cerrando conexion MySQL: {e}")
            finally:
                self.connection = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
