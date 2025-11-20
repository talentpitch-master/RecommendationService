"""
Gestor de tunel SSH para conexion a base de datos remota.

Proporciona conexion automatica a traves de bastion host.
"""
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sshtunnel import SSHTunnelForwarder

from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class SSHTunnelManager:
    """
    Gestor singleton de tunel SSH para acceso a base de datos.

    Maneja conexion automatica a traves de bastion host usando
    credenciales de carpeta credentials/.
    """

    _instance: Optional['SSHTunnelManager'] = None
    _tunnel: Optional[SSHTunnelForwarder] = None
    _initialized: bool = False

    def __new__(cls) -> 'SSHTunnelManager':
        """
        Crea nueva instancia usando patron singleton.

        Returns:
            Instancia unica de SSHTunnelManager
        """
        if cls._instance is None:
            cls._instance = super(SSHTunnelManager, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Inicializa gestor de tunel SSH.

        Solo se ejecuta una vez gracias al patron singleton.
        """
        if self._initialized:
            return

        self._initialized = True
        self._load_ssh_credentials()

    def _load_ssh_credentials(self) -> None:
        """
        Carga credenciales SSH desde credentials/.env sin afectar env global.
        """
        credentials_path = Path(__file__).parent.parent / 'credentials'
        env_file = credentials_path / '.env'

        if not env_file.exists():
            logger.warning(f"No se encontro {env_file}")
            return

        ssh_config = {}
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    ssh_config[key.strip()] = value.strip()

        logger.info(f"Credenciales SSH cargadas desde {env_file}")

        self.ssh_host = ssh_config.get('SSH_HOST')
        self.ssh_user = ssh_config.get('SSH_USER')
        self.mysql_host = ssh_config.get('MYSQL_HOST')
        self.mysql_port = int(ssh_config.get('MYSQL_PORT', '3306'))

        cert_files = list(credentials_path.glob('*.cer')) + list(credentials_path.glob('*.pem'))
        self.ssh_key_file = str(cert_files[0]) if cert_files else None

    def start_tunnel(self, local_port: int = 3307) -> None:
        """
        Inicia tunel SSH si no esta activo.

        Args:
            local_port: Puerto local para el tunel

        Raises:
            ValueError: Si faltan credenciales SSH
            Exception: Si falla la conexion SSH
        """
        if self._tunnel and self._tunnel.is_active:
            logger.info("Tunel SSH ya activo")
            return

        if not all([self.ssh_host, self.ssh_user, self.mysql_host, self.ssh_key_file]):
            raise ValueError(
                "Credenciales SSH incompletas. "
                "Verifica credentials/.env y archivo .cer/.pem"
            )

        logger.info(
            f"Iniciando tunel SSH: {self.ssh_host} -> "
            f"{self.mysql_host}:{self.mysql_port}"
        )

        try:
            self._tunnel = SSHTunnelForwarder(
                self.ssh_host,
                ssh_username=self.ssh_user,
                ssh_pkey=self.ssh_key_file,
                remote_bind_address=(self.mysql_host, self.mysql_port),
                local_bind_address=('127.0.0.1', local_port)
            )

            self._tunnel.start()

            logger.info(
                f"Tunel SSH activo: localhost:{local_port} -> "
                f"{self.mysql_host}:{self.mysql_port}"
            )

        except Exception as e:
            logger.error(f"Error iniciando tunel SSH: {e}")
            raise

    def stop_tunnel(self) -> None:
        """
        Detiene tunel SSH si esta activo.
        """
        if self._tunnel and self._tunnel.is_active:
            self._tunnel.stop()
            logger.info("Tunel SSH detenido")

    def is_active(self) -> bool:
        """
        Verifica si tunel SSH esta activo.

        Returns:
            True si tunel activo, False si no
        """
        return self._tunnel is not None and self._tunnel.is_active

    def __enter__(self) -> 'SSHTunnelManager':
        """
        Soporte para context manager.

        Returns:
            Instancia con tunel activo
        """
        self.start_tunnel()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Cierra tunel al salir del context manager.

        Args:
            exc_type: Tipo de excepcion si ocurrio
            exc_val: Valor de excepcion si ocurrio
            exc_tb: Traceback de excepcion si ocurrio

        Returns:
            False para propagar excepciones
        """
        self.stop_tunnel()
        return False
