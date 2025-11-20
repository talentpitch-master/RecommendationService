import json
import time
from datetime import datetime
from typing import Any, Dict, Optional, Set

from core.cache import RedisConnection
from core.config import Config
from core.database import MySQLConnection
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class ActivityTracker:
    """
    Tracker singleton de actividades de usuarios en Redis.

    Rastrea vistas de videos y requests de feed con flush a MySQL.
    Usa TTL configurable para actividades y sesiones.
    """

    _instance: Optional['ActivityTracker'] = None
    _initialized: bool = False

    def __new__(cls) -> 'ActivityTracker':
        """
        Crea nueva instancia usando patron singleton.

        Returns:
            Instancia unica de ActivityTracker
        """
        if cls._instance is None:
            cls._instance = super(ActivityTracker, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Inicializa tracker de actividades.

        Solo se ejecuta una vez gracias al patron singleton.
        """
        if self._initialized:
            return

        self._initialized = True
        self.redis_conn: Optional[RedisConnection] = None
        self.redis_client: Optional[Any] = None
        self.config = Config()
        self._connect_redis()
        logger.info("ActivityTracker inicializado")

    def _connect_redis(self) -> None:
        """
        Establece conexion a Redis usando RedisConnection singleton.
        """
        try:
            self.redis_conn = RedisConnection()
            self.redis_conn.connect()
            self.redis_client = self.redis_conn.connection
            logger.info("Redis conectado para activity tracking")
        except Exception as e:
            logger.error(f"Error conectando a Redis: {e}")
            self.redis_client = None

    def track_video_view(
        self,
        user_id: int,
        video_id: int,
        video_url: str,
        position_in_feed: int,
        feed_type: str,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Registra vista de video en Redis.

        Args:
            user_id: ID del usuario
            video_id: ID del video
            video_url: URL del video
            position_in_feed: Posicion en el feed
            feed_type: Tipo de feed
            session_id: ID de sesion opcional

        Returns:
            True si se registro exitosamente
        """
        if not self.redis_client:
            return False

        try:
            session_key = (
                session_id if session_id
                else f"session:{user_id}:{int(time.time())}"
            )

            event_data = {
                'event_type': 'video_view',
                'user_id': user_id,
                'video_id': video_id,
                'video_url': video_url,
                'position': position_in_feed,
                'feed_type': feed_type,
                'timestamp': datetime.now().isoformat(),
                'session_id': session_key
            }

            user_activity_key = f"user_activity:{user_id}"
            self.redis_client.lpush(user_activity_key, json.dumps(event_data))
            self.redis_client.expire(
                user_activity_key,
                self.config.ACTIVITY_TTL_SECONDS
            )

            session_key_videos = f"{session_key}:videos"
            self.redis_client.sadd(session_key_videos, video_id)
            self.redis_client.expire(
                session_key_videos,
                self.config.SESSION_TTL_SECONDS
            )

            logger.debug(f"Video view tracked: user={user_id}, video={video_id}")
            return True
        except Exception as e:
            logger.error(f"Error tracking video view: {e}")
            return False

    def track_feed_request(
        self,
        user_id: int,
        endpoint: str,
        params: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> bool:
        """
        Registra solicitud de feed en Redis.

        Args:
            user_id: ID del usuario
            endpoint: Endpoint del feed
            params: Parametros de la solicitud
            session_id: ID de sesion opcional

        Returns:
            True si se registro exitosamente
        """
        if not self.redis_client:
            return False

        try:
            session_key = (
                session_id if session_id
                else f"session:{user_id}:{int(time.time())}"
            )

            event_data = {
                'event_type': 'feed_request',
                'user_id': user_id,
                'endpoint': endpoint,
                'params': params,
                'timestamp': datetime.now().isoformat(),
                'session_id': session_key
            }

            user_activity_key = f"user_activity:{user_id}"
            self.redis_client.lpush(user_activity_key, json.dumps(event_data))
            self.redis_client.expire(
                user_activity_key,
                self.config.ACTIVITY_TTL_SECONDS
            )

            logger.debug(
                f"Feed request tracked: user={user_id}, endpoint={endpoint}"
            )
            return True
        except Exception as e:
            logger.error(f"Error tracking feed request: {e}")
            return False

    def get_user_session_videos(
        self,
        user_id: int,
        session_id: str
    ) -> Set[int]:
        """
        Obtiene set de IDs de videos vistos en sesion especifica.

        Args:
            user_id: ID del usuario
            session_id: ID de la sesion

        Returns:
            Set de IDs de videos vistos
        """
        if not self.redis_client:
            return set()

        try:
            session_key_videos = f"{session_id}:videos"
            videos = self.redis_client.smembers(session_key_videos)
            return set(int(v) for v in videos if str(v).isdigit())
        except Exception as e:
            logger.error(f"Error getting session videos: {e}")
            return set()

    def flush_user_activity_to_mysql(self, user_id: int) -> int:
        """
        Transfiere actividades de usuario desde Redis a MySQL.

        Args:
            user_id: ID del usuario

        Returns:
            Numero de actividades transferidas
        """
        if not self.redis_client:
            logger.warning("Redis not connected, cannot flush")
            return 0

        try:
            user_activity_key = f"user_activity:{user_id}"
            activities = self.redis_client.lrange(user_activity_key, 0, -1)

            if not activities:
                logger.info(f"No activities to flush for user {user_id}")
                return 0

            mysql = MySQLConnection()
            mysql.connect()

            inserted_count = 0

            for activity_json in activities:
                try:
                    activity = json.loads(activity_json)

                    log_name = 'app'
                    description = self._generate_description(activity)
                    url = self._generate_url(activity)
                    causer_id = activity.get('user_id')
                    causer_type = 'App\\User'
                    properties = json.dumps(activity)
                    created_at = activity.get('timestamp')

                    insert_query = """
                    INSERT INTO activity_log
                    (log_name, description, subject_id, subject_type,
                     causer_id, causer_type, properties, url,
                     created_at, updated_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    subject_id = activity.get('video_id')
                    subject_type = (
                        'App\\Interacpedia\\Resumes\\Resume'
                        if activity.get('event_type') == 'video_view'
                        else None
                    )

                    mysql.execute_query(insert_query, (
                        log_name,
                        description,
                        subject_id,
                        subject_type,
                        causer_id,
                        causer_type,
                        properties,
                        url,
                        created_at,
                        created_at
                    ))

                    inserted_count += 1
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f"Error inserting activity: {e}")
                    continue

            mysql.close()

            self.redis_client.delete(user_activity_key)

            logger.info(f"Flushed {inserted_count} activities for user {user_id}")
            return inserted_count

        except Exception as e:
            logger.error(f"Error flushing user activity: {e}")
            return 0

    def _generate_description(self, activity: Dict[str, Any]) -> str:
        """
        Genera descripcion formateada para actividad segun tipo.

        Args:
            activity: Diccionario con datos de la actividad

        Returns:
            Descripcion formateada con tags
        """
        event_type = activity.get('event_type')

        if event_type == 'video_view':
            feed_type = activity.get('feed_type', 'feed')
            return f"#video #view #{feed_type}"
        elif event_type == 'feed_request':
            endpoint = activity.get('endpoint', 'feed')
            return f"#feed #request #{endpoint}"

        return "#activity"

    def _generate_url(self, activity: Dict[str, Any]) -> str:
        """
        Genera URL del endpoint asociado a actividad.

        Args:
            activity: Diccionario con datos de la actividad

        Returns:
            URL del endpoint
        """
        event_type = activity.get('event_type')

        if event_type == 'video_view':
            video_id = activity.get('video_id')
            return f"/api/search/feed/video/{video_id}"
        elif event_type == 'feed_request':
            endpoint = activity.get('endpoint')
            return f"/api/search/{endpoint}"

        return "/api/search"

    def flush_all_pending_activities(self) -> int:
        """
        Ejecuta flush masivo de todas las actividades pendientes.

        Returns:
            Numero total de actividades transferidas
        """
        if not self.redis_client:
            return 0

        try:
            pattern = "user_activity:*"
            user_keys = list(self.redis_client.scan_iter(match=pattern))

            total_flushed = 0

            for key in user_keys:
                user_id_str = (
                    key.decode('utf-8').split(':')[1]
                    if isinstance(key, bytes)
                    else key.split(':')[1]
                )
                if user_id_str.isdigit():
                    count = self.flush_user_activity_to_mysql(int(user_id_str))
                    total_flushed += count

            logger.info(f"Total activities flushed: {total_flushed}")
            return total_flushed
        except Exception as e:
            logger.error(f"Error flushing all activities: {e}")
            return 0

    def close(self) -> None:
        """
        Cierra conexion a Redis y libera recursos.
        """
        if self.redis_conn:
            self.redis_conn.close()
            logger.info("Redis connection closed")
