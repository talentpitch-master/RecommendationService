import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from queue import Queue, Empty
from threading import Lock

import pymysql
from dotenv import load_dotenv

from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class ConnectionPool:
    """
    Pool de conexiones MySQL para reutilizacion eficiente.

    Mantiene un pool de conexiones activas que pueden ser reutilizadas
    en lugar de crear/cerrar conexiones en cada request.

    Implementacion thread-safe usando Queue.
    """

    def __init__(
        self,
        pool_size: int,
        host: str,
        port: int,
        user: str,
        password: Optional[str],
        database: str
    ):
        """
        Inicializa pool de conexiones.

        Args:
            pool_size: Numero de conexiones en el pool
            host: Host de MySQL
            port: Puerto de MySQL
            user: Usuario de MySQL
            password: Password de MySQL
            database: Nombre de base de datos
        """
        self.pool_size = pool_size
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

        # Pool de conexiones usando Queue (thread-safe)
        self._pool: Queue = Queue(maxsize=pool_size)
        self._lock = Lock()
        self._created_connections = 0

        # Pre-crear conexiones
        self._initialize_pool()

        logger.info(
            f"Connection pool inicializado: {pool_size} conexiones a "
            f"{host}:{port}/{database}"
        )

    def _create_connection(self) -> pymysql.connections.Connection:
        """
        Crea nueva conexion MySQL.

        Returns:
            Nueva conexion MySQL
        """
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            db=self.database,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=30,
            read_timeout=60,
            write_timeout=60,
            autocommit=False
        )

    def _initialize_pool(self) -> None:
        """
        Pre-crea conexiones para llenar el pool.
        """
        for _ in range(self.pool_size):
            try:
                conn = self._create_connection()
                self._pool.put(conn)
                self._created_connections += 1
            except Exception as e:
                logger.error(f"Error creando conexion para pool: {e}")
                raise

    def get_connection(self, timeout: int = 30) -> pymysql.connections.Connection:
        """
        Obtiene conexion del pool.

        Si el pool esta vacio, espera hasta timeout segundos.
        Si todas las conexiones estan en uso y timeout expira, crea nueva conexion.

        Args:
            timeout: Segundos a esperar por conexion disponible

        Returns:
            Conexion MySQL del pool
        """
        try:
            # Intentar obtener conexion del pool
            conn = self._pool.get(timeout=timeout)

            # Verificar que conexion este viva
            try:
                conn.ping(reconnect=True)
                return conn
            except:
                # Conexion muerta, crear nueva
                logger.warning("Conexion muerta en pool, creando nueva")
                return self._create_connection()

        except Empty:
            # Pool vacio y timeout expirado
            logger.warning(
                f"Pool vacio despues de {timeout}s, creando conexion adicional"
            )
            with self._lock:
                self._created_connections += 1
                logger.info(
                    f"Conexiones creadas: {self._created_connections} "
                    f"(pool size: {self.pool_size})"
                )
            return self._create_connection()

    def return_connection(self, conn: pymysql.connections.Connection) -> None:
        """
        Devuelve conexion al pool.

        Args:
            conn: Conexion a devolver
        """
        try:
            # Verificar que conexion este viva
            conn.ping(reconnect=True)

            # Si el pool no esta lleno, devolver conexion
            if not self._pool.full():
                self._pool.put_nowait(conn)
            else:
                # Pool lleno, cerrar conexion extra
                conn.close()

        except Exception as e:
            logger.warning(f"Error devolviendo conexion a pool: {e}")
            try:
                conn.close()
            except:
                pass

    def close_all(self) -> None:
        """
        Cierra todas las conexiones del pool.
        """
        closed_count = 0
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
                closed_count += 1
            except:
                break

        logger.info(f"Pool cerrado: {closed_count} conexiones cerradas")


class MySQLConnection:
    """
    Conexion singleton a MySQL con connection pooling.

    Utiliza patron singleton para mantener un pool de conexiones compartido.
    Connection pooling mejora performance al reutilizar conexiones.
    """

    _instance: Optional['MySQLConnection'] = None
    _initialized: bool = False
    _pool: Optional[ConnectionPool] = None

    def __new__(cls) -> 'MySQLConnection':
        """
        Crea nueva instancia usando patron singleton.

        Returns:
            Instancia unica de MySQLConnection
        """
        if cls._instance is None:
            cls._instance = super(MySQLConnection, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Inicializa conexion MySQL con pooling.

        Solo se ejecuta una vez gracias al patron singleton.
        """
        if self._initialized:
            return

        self._initialized = True
        self.connection: Optional[pymysql.connections.Connection] = None
        self._use_pooling: bool = True  # Flag para habilitar/deshabilitar pooling
        self._load_credentials()

    def _load_credentials(self) -> None:
        """
        Carga credenciales desde archivo .env.

        Raises:
            FileNotFoundError: Si no encuentra archivo .env
        """
        current_file = Path(__file__).resolve()
        project_root = current_file.parent.parent
        env_path = project_root / 'credentials' / '.env'

        if not env_path.exists():
            raise FileNotFoundError(
                f"No se encontro .env en credentials: {env_path}"
            )

        load_dotenv(env_path)
        logger.info(f"Credenciales cargadas desde: {env_path}")

    def connect(self, pool_size: int = 20, use_pooling: bool = True) -> pymysql.connections.Connection:
        """
        Establece conexion a MySQL usando connection pooling.

        Si pooling esta habilitado, inicializa pool de conexiones una sola vez.
        Si pooling esta deshabilitado, crea conexion directa (compatibilidad).

        Args:
            pool_size: Tamano del connection pool (default: 20)
            use_pooling: Si True, usa pooling. Si False, conexion directa (default: True)

        Returns:
            Conexion establecida a MySQL

        Raises:
            ValueError: Si faltan variables de entorno requeridas
            Exception: Si falla la conexion a MySQL
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
            raise ValueError(
                f"Variables de entorno faltantes: {', '.join(missing)}"
            )

        self._use_pooling = use_pooling

        if use_pooling:
            # Inicializar connection pool si no existe
            if MySQLConnection._pool is None:
                logger.info(
                    f"Inicializando connection pool - Host: {mysql_host}:{mysql_port}, "
                    f"DB: {mysql_db}, Pool Size: {pool_size}"
                )
                try:
                    MySQLConnection._pool = ConnectionPool(
                        pool_size=pool_size,
                        host=mysql_host,
                        port=mysql_port,
                        user=mysql_user,
                        password=mysql_password,
                        database=mysql_db
                    )
                    logger.info("Connection pool inicializado exitosamente")
                except Exception as e:
                    logger.error(f"Error inicializando connection pool: {e}")
                    raise

            # Obtener conexion del pool
            self.connection = MySQLConnection._pool.get_connection()
            logger.debug("Conexion obtenida del pool")
            return self.connection

        else:
            # Modo sin pooling (compatibilidad con codigo existente)
            logger.info(
                f"Conectando a MySQL SIN pooling - Host: {mysql_host}:{mysql_port}, "
                f"DB: {mysql_db}"
            )

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
                logger.info("Conexion MySQL directa establecida exitosamente")
                return self.connection
            except Exception as e:
                logger.error(f"Error conectando a MySQL: {e}")
                raise

    def execute_query(
        self,
        query: str,
        params: Optional[Tuple[Any, ...]] = None
    ) -> Any:
        """
        Ejecuta query SQL en MySQL.

        Args:
            query: Query SQL a ejecutar
            params: Parametros para query preparado

        Returns:
            Lista de diccionarios para SELECT o numero de filas afectadas

        Raises:
            RuntimeError: Si no hay conexion establecida
            Exception: Si falla la ejecucion del query
        """
        if not self.connection:
            raise RuntimeError(
                "No hay conexion establecida. Llama a connect() primero."
            )

        try:
            with self.connection.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                query_type = query.strip().upper().split()[0]

                if query_type in ('SELECT', 'SHOW', 'DESCRIBE', 'DESC', 'EXPLAIN'):
                    results = cursor.fetchall()
                    logger.debug(
                        f"Query SELECT ejecutada: {len(results)} filas obtenidas"
                    )
                    return results
                else:
                    self.connection.commit()
                    affected = cursor.rowcount
                    logger.debug(
                        f"Query {query_type} ejecutada: {affected} filas afectadas"
                    )
                    return affected
        except Exception as e:
            logger.error(f"Error ejecutando query: {e}")
            logger.debug(f"Query: {query[:200]}...")
            raise

    def close(self) -> None:
        """
        Cierra o devuelve la conexion al pool.

        Si usa pooling, devuelve conexion al pool para reutilizacion.
        Si no usa pooling, cierra conexion directamente.
        """
        if self.connection:
            try:
                if self._use_pooling and MySQLConnection._pool is not None:
                    # Devolver conexion al pool
                    MySQLConnection._pool.return_connection(self.connection)
                    logger.debug("Conexion devuelta al pool")
                else:
                    # Cerrar conexion directamente
                    self.connection.close()
                    logger.info("Conexion MySQL cerrada")
            except Exception as e:
                logger.error(f"Error cerrando/devolviendo conexion MySQL: {e}")
            finally:
                self.connection = None

    @classmethod
    def close_pool(cls) -> None:
        """
        Cierra el connection pool completamente.

        Util para shutdown limpio de la aplicacion.
        """
        if cls._pool is not None:
            cls._pool.close_all()
            cls._pool = None
            logger.info("Connection pool cerrado completamente")

    def __enter__(self) -> 'MySQLConnection':
        """
        Soporte para context manager.

        Returns:
            Instancia de MySQLConnection con conexion activa
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
