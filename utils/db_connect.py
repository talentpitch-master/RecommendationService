"""
SCRIPT DE CONEXION A BASE DE DATOS

USO:
    from utils.db_connect import get_db_connection

    with get_db_connection() as conn:
        conn.execute_query("SELECT * FROM users LIMIT 1")

IMPORTANTE:
    - SIEMPRE usar SSHTunnelManager para tuneles SSH
    - SIEMPRE usar MySQLConnection para queries
    - NO inventar metodos nuevos de conexion
    - Este es el UNICO metodo correcto
"""

from core.ssh_tunnel import SSHTunnelManager
from core.database import MySQLConnection


def get_db_connection(use_pooling: bool = False):
    """
    Retorna conexion a BD con tunel SSH activo.

    Args:
        use_pooling: Si usar connection pooling

    Returns:
        MySQLConnection conectada

    Example:
        with get_db_connection() as conn:
            results = conn.execute_query("SELECT COUNT(*) FROM users")
            print(results)
    """
    # Iniciar tunel SSH
    tunnel = SSHTunnelManager()
    tunnel.start_tunnel()

    # Conectar a BD
    conn = MySQLConnection()
    conn.connect(use_pooling=use_pooling)

    return conn, tunnel


if __name__ == '__main__':
    # Ejemplo de uso
    print("Probando conexion...")
    conn, tunnel = get_db_connection()

    try:
        result = conn.execute_query("SELECT COUNT(*) as count FROM users")
        print(f"Usuarios en BD: {result[0]['count']}")
        print("Conexion OK")
    finally:
        conn.close()
        tunnel.stop_tunnel()
