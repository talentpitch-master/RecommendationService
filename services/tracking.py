import json
import time
import redis
from datetime import datetime
from pathlib import Path
from core.cache import RedisConnection
from core.database import MySQLConnection
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

class ActivityTracker:
    """
    Tracker singleton de actividades de usuarios en Redis.
    Rastrea vistas de videos y requests de feed, luego flush a MySQL.
    Usa TTL de 24h para actividades y 1h para sesiones.
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ActivityTracker, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if ActivityTracker._initialized:
            return

        ActivityTracker._initialized = True
        self.redis_conn = None
        self.redis_client = None
        self._connect_redis()
        logger.info("ActivityTracker inicializado")

    def _connect_redis(self):
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

    def track_video_view(self, user_id, video_id, video_url, position_in_feed, feed_type, session_id=None):
        """
        Registra vista de video en Redis.
        Guarda en user_activity key con TTL 24h y en session key con TTL 1h.
        """
        if not self.redis_client:
            return False

        try:
            session_key = session_id if session_id else f"session:{user_id}:{int(time.time())}"

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
            self.redis_client.expire(user_activity_key, 86400)

            session_key_videos = f"{session_key}:videos"
            self.redis_client.sadd(session_key_videos, video_id)
            self.redis_client.expire(session_key_videos, 3600)

            logger.debug(f"Video view tracked: user={user_id}, video={video_id}")
            return True
        except Exception as e:
            logger.error(f"Error tracking video view: {e}")
            return False

    def track_feed_request(self, user_id, endpoint, params, session_id=None):
        """
        Registra solicitud de feed en Redis.
        Guarda endpoint y parametros en user_activity key con TTL 24h.
        """
        if not self.redis_client:
            return False

        try:
            session_key = session_id if session_id else f"session:{user_id}:{int(time.time())}"

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
            self.redis_client.expire(user_activity_key, 86400)

            logger.debug(f"Feed request tracked: user={user_id}, endpoint={endpoint}")
            return True
        except Exception as e:
            logger.error(f"Error tracking feed request: {e}")
            return False

    def get_user_session_videos(self, user_id, session_id):
        """
        Obtiene set de IDs de videos vistos en una sesion especifica.
        Retorna set vacio si no hay conexion o no hay datos.
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

    def flush_user_activity_to_mysql(self, user_id):
        """
        Transfiere actividades de un usuario desde Redis a tabla activity_log en MySQL.
        Elimina datos de Redis despues de transferencia exitosa.
        Retorna numero de actividades transferidas.
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
                    (log_name, description, subject_id, subject_type, causer_id, causer_type, properties, url, created_at, updated_at)
                    VALUES
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """

                    subject_id = activity.get('video_id')
                    subject_type = 'App\\Interacpedia\\Resumes\\Resume' if activity.get('event_type') == 'video_view' else None

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
                except Exception as e:
                    logger.error(f"Error inserting activity: {e}")
                    continue

            mysql.close()

            self.redis_client.delete(user_activity_key)

            logger.info(f"Flushed {inserted_count} activities for user {user_id}")
            return inserted_count

        except Exception as e:
            logger.error(f"Error flushing user activity: {e}")
            return 0

    def _generate_description(self, activity):
        """
        Genera descripcion formateada para la actividad segun su tipo.
        Retorna tags en formato #video #view #feed_type o #feed #request #endpoint.
        """
        event_type = activity.get('event_type')

        if event_type == 'video_view':
            feed_type = activity.get('feed_type', 'feed')
            return f"#video #view #{feed_type}"
        elif event_type == 'feed_request':
            endpoint = activity.get('endpoint', 'feed')
            return f"#feed #request #{endpoint}"

        return "#activity"

    def _generate_url(self, activity):
        """
        Genera URL del endpoint asociado a la actividad segun su tipo.
        Retorna ruta del API correspondiente a video_view o feed_request.
        """
        event_type = activity.get('event_type')

        if event_type == 'video_view':
            video_id = activity.get('video_id')
            return f"/api/search/feed/video/{video_id}"
        elif event_type == 'feed_request':
            endpoint = activity.get('endpoint')
            return f"/api/search/{endpoint}"

        return "/api/search"

    def flush_all_pending_activities(self):
        """
        Ejecuta flush masivo de todas las actividades pendientes en Redis a MySQL.
        Escanea todas las keys user_activity:* y transfiere sus datos.
        Retorna numero total de actividades transferidas.
        """
        if not self.redis_client:
            return 0

        try:
            pattern = "user_activity:*"
            user_keys = list(self.redis_client.scan_iter(match=pattern))

            total_flushed = 0

            for key in user_keys:
                user_id = key.decode('utf-8').split(':')[1] if isinstance(key, bytes) else key.split(':')[1]
                if user_id.isdigit():
                    count = self.flush_user_activity_to_mysql(int(user_id))
                    total_flushed += count

            logger.info(f"Total activities flushed: {total_flushed}")
            return total_flushed
        except Exception as e:
            logger.error(f"Error flushing all activities: {e}")
            return 0

    def close(self):
        """
        Cierra la conexion a Redis y libera recursos.
        Debe llamarse al finalizar el uso del tracker.
        """
        if self.redis_conn:
            self.redis_conn.close()
            logger.info("Redis connection closed")
