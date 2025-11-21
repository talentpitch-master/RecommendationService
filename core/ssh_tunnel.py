"""
Gestor de tunel SSH para conexion a base de datos remota.

Proporciona conexion automatica a traves de bastion host.
"""
import socket
import threading
from pathlib import Path
from typing import Optional

import paramiko
from dotenv import load_dotenv

from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class SSHTunnelManager:
    """
    Gestor singleton de tunel SSH para acceso a base de datos.

    Maneja conexion automatica a traves de bastion host usando
    credenciales de carpeta credentials/.
    """

    _instance: Optional['SSHTunnelManager'] = None
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
        self._ssh_client: Optional[paramiko.SSHClient] = None
        self._transport: Optional[paramiko.Transport] = None
        self._server_thread: Optional[threading.Thread] = None
        self._local_port: Optional[int] = None
        self._stop_flag = threading.Event()
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

    def _forward_tunnel(self, local_port: int) -> None:
        """
        Maneja el port forwarding del tunel SSH.

        Args:
            local_port: Puerto local para escuchar conexiones
        """
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server.bind(('127.0.0.1', local_port))
        except OSError as e:
            if e.errno == 98:  # Address already in use
                logger.info(f"Puerto {local_port} ya en uso - otro worker maneja el tunel")
                server.close()
                return
            raise

        server.listen(5)
        server.settimeout(1.0)

        logger.info(f"Tunel SSH escuchando en localhost:{local_port}")

        while not self._stop_flag.is_set():
            try:
                client_sock, addr = server.accept()
                logger.debug(f"Nueva conexion desde {addr}")

                # Crear canal SSH para forward
                transport = self._ssh_client.get_transport()
                remote_addr = (self.mysql_host, self.mysql_port)
                local_addr = ('127.0.0.1', local_port)

                channel = transport.open_channel(
                    'direct-tcpip',
                    remote_addr,
                    local_addr
                )

                # Forward data bidireccional
                self._forward_data(client_sock, channel)

            except socket.timeout:
                continue
            except Exception as e:
                if not self._stop_flag.is_set():
                    logger.error(f"Error en port forwarding: {e}")

        server.close()
        logger.info("Servidor de tunel SSH detenido")

    def _forward_data(self, client: socket.socket, channel: paramiko.Channel) -> None:
        """
        Forward data entre socket local y canal SSH.

        Args:
            client: Socket del cliente local
            channel: Canal SSH remoto
        """
        def forward_client_to_remote():
            try:
                while True:
                    data = client.recv(4096)
                    if len(data) == 0:
                        break
                    channel.send(data)
            except Exception:
                pass
            finally:
                channel.close()

        def forward_remote_to_client():
            try:
                while True:
                    data = channel.recv(4096)
                    if len(data) == 0:
                        break
                    client.send(data)
            except Exception:
                pass
            finally:
                client.close()

        t1 = threading.Thread(target=forward_client_to_remote, daemon=True)
        t2 = threading.Thread(target=forward_remote_to_client, daemon=True)
        t1.start()
        t2.start()

    def start_tunnel(self, local_port: int = 3307) -> None:
        """
        Inicia tunel SSH si no esta activo.

        Args:
            local_port: Puerto local para el tunel

        Raises:
            ValueError: Si faltan credenciales SSH
            Exception: Si falla la conexion SSH
        """
        if self.is_active():
            logger.info("Tunel SSH ya activo en este worker")
            return

        # Verificar si otro worker ya inicio el tunel
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.settimeout(0.5)
            result = test_sock.connect_ex(('127.0.0.1', local_port))
            test_sock.close()

            if result == 0:
                logger.info(f"Tunel SSH ya disponible en puerto {local_port} (manejado por otro worker)")
                # No crear conexion SSH, usar el tunel existente
                return
        except Exception:
            pass

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
            # Crear cliente SSH
            self._ssh_client = paramiko.SSHClient()
            self._ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Cargar llave privada
            try:
                private_key = paramiko.RSAKey.from_private_key_file(self.ssh_key_file)
            except paramiko.ssh_exception.SSHException:
                try:
                    private_key = paramiko.ECDSAKey.from_private_key_file(self.ssh_key_file)
                except paramiko.ssh_exception.SSHException:
                    private_key = paramiko.Ed25519Key.from_private_key_file(self.ssh_key_file)

            # Conectar al bastion
            self._ssh_client.connect(
                hostname=self.ssh_host,
                username=self.ssh_user,
                pkey=private_key,
                timeout=10
            )

            self._local_port = local_port
            self._stop_flag.clear()

            # Iniciar thread de port forwarding
            self._server_thread = threading.Thread(
                target=self._forward_tunnel,
                args=(local_port,),
                daemon=True
            )
            self._server_thread.start()

            logger.info(
                f"Tunel SSH activo: localhost:{local_port} -> "
                f"{self.mysql_host}:{self.mysql_port}"
            )

        except Exception as e:
            logger.error(f"Error iniciando tunel SSH: {e}")
            self._cleanup()
            raise

    def _cleanup(self) -> None:
        """Limpia recursos del tunel."""
        if self._ssh_client:
            self._ssh_client.close()
            self._ssh_client = None
        self._transport = None
        self._server_thread = None

    def stop_tunnel(self) -> None:
        """
        Detiene tunel SSH si esta activo.
        """
        if self.is_active():
            self._stop_flag.set()
            if self._server_thread:
                self._server_thread.join(timeout=5)
            self._cleanup()
            logger.info("Tunel SSH detenido")

    def is_active(self) -> bool:
        """
        Verifica si tunel SSH esta activo.

        Returns:
            True si tunel activo, False si no
        """
        return (
            self._ssh_client is not None
            and self._ssh_client.get_transport() is not None
            and self._ssh_client.get_transport().is_active()
        )

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
