import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict

class LoggerConfig:
    """
    Configuracion centralizada de logging para toda la aplicacion.
    Implementa patron singleton para loggers con timezone GMT-5.
    Configura formato, archivo de log y niveles para diferentes modulos.
    """
    _loggers: Dict[str, logging.Logger] = {}
    _initialized: bool = False

    @staticmethod
    def setup_logging(log_dir: str = 'logs', version_name: Optional[str] = None) -> None:
        """
        Configura el sistema de logging global con formato GMT-5.

        Args:
            log_dir: Directorio donde se guardaran los archivos de log
            version_name: Version opcional (no usado actualmente)

        Note:
            Solo se ejecuta una vez gracias al flag _initialized
        """
        if LoggerConfig._initialized:
            return

        os.makedirs(log_dir, exist_ok=True)

        log_file = os.path.join(log_dir, 'talent.log')

        class GMT5Formatter(logging.Formatter):
            """
            Formatter personalizado con timezone GMT-5 (Colombia/Bogota).
            Convierte timestamps UTC a GMT-5 para logs localizados.
            """
            def converter(self, timestamp: float) -> datetime:
                """
                Convierte timestamp Unix a datetime en GMT-5.

                Args:
                    timestamp: Timestamp Unix en segundos

                Returns:
                    Objeto datetime en timezone GMT-5
                """
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                return dt.astimezone(timezone(timedelta(hours=-5)))

            def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
                """
                Formatea timestamp del log record usando GMT-5.

                Args:
                    record: Log record con timestamp a formatear
                    datefmt: Formato de fecha opcional (strftime)

                Returns:
                    String con fecha/hora formateada
                """
                dt = self.converter(record.created)
                if datefmt:
                    s = dt.strftime(datefmt)
                else:
                    s = dt.strftime('%Y-%m-%d %H:%M:%S')
                return s

        formatter = GMT5Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)

        logging.getLogger('paramiko').setLevel(logging.WARNING)

        LoggerConfig._initialized = True

    @staticmethod
    def get_logger(name: str, version_name: Optional[str] = None) -> logging.Logger:
        """
        Obtiene o crea un logger por nombre.

        Args:
            name: Nombre del logger (usualmente __name__ del modulo)
            version_name: Version opcional (no usado actualmente)

        Returns:
            Instancia de logger para el modulo especificado
        """
        if not LoggerConfig._initialized:
            LoggerConfig.setup_logging()

        if name not in LoggerConfig._loggers:
            LoggerConfig._loggers[name] = logging.getLogger(name)

        return LoggerConfig._loggers[name]
