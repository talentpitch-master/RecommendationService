import pandas as pd
from pathlib import Path
from datetime import datetime
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class DataService:
    """
    Servicio singleton para carga y gestion de datos desde MySQL.
    Carga usuarios, videos, flows, interacciones y conexiones en DataFrames de Pandas.
    Implementa blacklist de URLs a nivel SQL.
    """
    _instancia = None
    _inicializado = False

    def __new__(cls, connection_factory=None):
        if cls._instancia is None:
            cls._instancia = super(DataService, cls).__new__(cls)
        return cls._instancia

    def __init__(self, connection_factory=None):
        if DataService._inicializado:
            return

        if connection_factory is None:
            raise ValueError("connection_factory requerido en primera inicializacion")

        self.connection_factory = connection_factory
        self.users_df = None
        self.videos_df = None
        self.interactions_df = None
        self.connections_df = None
        self.flows_df = None
        self._conn = None
        self.lista_negra = self._cargar_lista_negra()
        DataService._inicializado = True

    def _cargar_lista_negra(self):
        """
        Carga lista de URLs bloqueadas desde data/blacklist.csv.
        Retorna set de URLs a excluir en las queries SQL.
        """
        lista_negra_path = Path('data/blacklist.csv')

        urls_bloqueadas = set()

        if not lista_negra_path.exists():
            logger.warning(f"No se encontro data/blacklist.csv")
            return urls_bloqueadas

        try:
            with open(lista_negra_path, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
                for linea in lineas:
                    url = linea.strip()
                    if url and not url.startswith('#'):
                        urls_bloqueadas.add(url)

            logger.info(f"Lista negra cargada: {len(urls_bloqueadas)} URLs bloqueadas")
        except Exception as e:
            logger.error(f"Error cargando lista negra: {e}")

        return urls_bloqueadas

    def load_all_data(self):
        """
        Carga todos los datos desde MySQL a DataFrames en memoria.
        Establece conexion y ejecuta carga de usuarios, videos, flows, interacciones y conexiones.
        """
        logger.info("Iniciando carga de datos")
        self._conn = self.connection_factory()
        self._conn.connect()

        try:
            self.users_df = self._load_users()
            self.videos_df = self._load_videos()
            self.interactions_df = self._load_interactions()
            self.connections_df = self._load_connections()
            self.flows_df = self._load_flows()
            logger.info("Carga de datos completada")
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
            raise

    def _execute_query(self, query, params=None):
        """
        Ejecuta query SQL y retorna resultados.
        """
        if not self._conn or not self._conn.connection:
            raise RuntimeError("No hay conexion establecida")

        results = self._conn.execute_query(query, params)
        return results

    def _normalize_city(self, city, country):
        """
        Normaliza nombres de ciudades aplicando mapeo estandar.
        Retorna ciudad normalizada o 'Unknown' si no hay datos validos.
        """
        if not city or city == '':
            if country and country != '':
                return f"Other-{country}"
            return "Unknown"

        city = city.strip()

        city_mapping = {
            'Bogotá': 'Bogotá',
            'Bogotá D.C.': 'Bogotá',
            'Bogota': 'Bogotá',
            'bogota': 'Bogotá',
            'Medellin': 'Medellín',
            'medellin': 'Medellín',
            'Cali': 'Cali',
            'cali': 'Cali',
            'Barranquilla': 'Barranquilla',
            'barranquilla': 'Barranquilla',
            'Bucaramanga': 'Bucaramanga',
            'Distrito Federal': 'CDMX',
            'Ciudad de México': 'CDMX',
            'Nuevo Leon': 'Monterrey',
            'Nuevo León': 'Monterrey'
        }

        return city_mapping.get(city, city)

    def _load_users(self):
        """
        Carga usuarios desde tabla users con datos de perfiles.
        Incluye skills, languages, tools, knowledge y objetivos.
        """
        query = """
        SELECT
            u.id,
            u.name,
            COALESCE(NULLIF(TRIM(u.city), ''), 'Unknown') as city,
            COALESCE(NULLIF(TRIM(u.country), ''), 'Unknown') as country,
            u.created_at,
            p.skills,
            p.languages,
            p.tools,
            p.knowledge,
            p.hobbies,
            p.type_talentees,
            p.opencall_objective
        FROM users u
        LEFT JOIN profiles p ON u.id = p.user_id
        WHERE u.deleted_at IS NULL
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)
        logger.info(f"Usuarios cargados: {len(df)}")
        return df

    def _load_videos(self):
        """
        Carga videos/resumes desde tabla resumes con metricas de engagement.
        Aplica blacklist a nivel SQL y calcula scores normalizados.
        Incluye ratings, connections, likes, exhibited y views.
        """
        lista_negra_sql = ','.join([f"'{url.replace('%', '%%')}'" for url in self.lista_negra]) if self.lista_negra else "''"

        query = f"""
        SELECT /*+ MAX_EXECUTION_TIME(60000) */
            r.id,
            r.user_id,
            r.video,
            r.views,
            r.skills as video_skills,
            r.knowledges as video_knowledges,
            r.tools as video_tools,
            r.languages as video_languages,
            r.role_objectives,
            r.created_at,
            r.description,
            COALESCE(NULLIF(TRIM(u.city), ''), '') as creator_city,
            COALESCE(NULLIF(TRIM(u.country), ''), '') as creator_country,
            COALESCE(u.name, '') as creator_name,
            CASE
                WHEN COALESCE(tf.avg_rating, 0) > 5 THEN 5.0
                ELSE COALESCE(tf.avg_rating, 0)
            END as avg_rating,
            COALESCE(tf.rating_count, 0) as rating_count,
            CASE WHEN tf.rating_count > 0 THEN 1 ELSE 0 END as has_rating,
            COALESCE(matches.match_count, 0) as connection_count,
            COALESCE(likes.like_count, 0) as like_count,
            COALESCE(exhibited.exhibited_count, 0) as exhibited_count,
            COALESCE(views_count.view_count, 0) as actual_views
        FROM resumes r
        STRAIGHT_JOIN users u ON r.user_id = u.id
        LEFT JOIN (
            SELECT
                model_id,
                AVG(CASE WHEN value > 5 THEN 5 ELSE value END) as avg_rating,
                COUNT(*) as rating_count
            FROM team_feedbacks
            WHERE type = 'ranking_resume'
            AND value > 0
            GROUP BY model_id
        ) tf ON tf.model_id = r.id
        LEFT JOIN (
            SELECT model_id, COUNT(*) as match_count
            FROM matches
            WHERE status = 'accepted'
            GROUP BY model_id
        ) matches ON matches.model_id = r.id
        LEFT JOIN (
            SELECT model_id, COUNT(*) as like_count
            FROM likes
            WHERE type = 'save'
            GROUP BY model_id
        ) likes ON likes.model_id = r.id
        LEFT JOIN (
            SELECT resume_id, COUNT(*) as exhibited_count
            FROM resumes_exhibited
            GROUP BY resume_id
        ) exhibited ON exhibited.resume_id = r.id
        LEFT JOIN (
            SELECT model_id, COUNT(*) as view_count
            FROM views
            WHERE model_type = 'App\\\\Interacpedia\\\\Resumes\\\\Resume'
            GROUP BY model_id
        ) views_count ON views_count.model_id = r.id
        WHERE r.deleted_at IS NULL
        AND r.status = 'send'
        AND r.video IS NOT NULL
        AND r.video NOT IN ({lista_negra_sql})
        AND u.deleted_at IS NULL
        AND (
            r.views >= 5
            OR tf.avg_rating >= 3.0
            OR matches.match_count >= 1
            OR exhibited.exhibited_count >= 1
        )
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)

        df['views'] = pd.to_numeric(df['actual_views'], errors='coerce').fillna(0).astype(int)
        df['avg_rating'] = pd.to_numeric(df['avg_rating'], errors='coerce').fillna(0).astype(float)
        df['rating_count'] = pd.to_numeric(df['rating_count'], errors='coerce').fillna(0).astype(int)
        df['has_rating'] = pd.to_numeric(df['has_rating'], errors='coerce').fillna(0).astype(int)
        df['connection_count'] = pd.to_numeric(df['connection_count'], errors='coerce').fillna(0).astype(int)
        df['like_count'] = pd.to_numeric(df['like_count'], errors='coerce').fillna(0).astype(int)
        df['exhibited_count'] = pd.to_numeric(df['exhibited_count'], errors='coerce').fillna(0).astype(int)

        df['city'] = df.apply(lambda row: self._normalize_city(row['creator_city'], row['creator_country']), axis=1)

        df['created_at'] = pd.to_datetime(df['created_at'])
        df['days_since_creation'] = (datetime.now() - df['created_at']).dt.days

        logger.info(f"Videos cargados: {len(df)}")
        logger.info(f"Videos con ciudad valida: {len(df[df['city'] != 'Unknown'])}")
        logger.info(f"Ciudades unicas: {df['city'].nunique()}")

        return df

    def _load_flows(self):
        """
        Carga challenges/flows desde tabla challenges.
        Filtra por status published, aplica blacklist y elimina duplicados por video URL.
        Solo incluye flows creados/actualizados desde 2025-01-01.
        """
        lista_negra_sql = ','.join([f"'{url.replace('%', '%%')}'" for url in self.lista_negra]) if self.lista_negra else "''"

        query = f"""
        SELECT
            c.id,
            c.user_id,
            c.video,
            c.name,
            c.description,
            c.created_at,
            COALESCE(u.name, '') as creator_name,
            COALESCE(NULLIF(TRIM(u.city), ''), '') as creator_city,
            COALESCE(NULLIF(TRIM(u.country), ''), '') as creator_country
        FROM (
            SELECT
                c2.id,
                c2.user_id,
                c2.video,
                c2.name,
                c2.description,
                c2.created_at,
                ROW_NUMBER() OVER (PARTITION BY c2.video ORDER BY c2.created_at DESC) as rn
            FROM challenges c2
            WHERE c2.deleted_at IS NULL
            AND c2.status = 'published'
            AND c2.video IS NOT NULL
            AND c2.video NOT IN ({lista_negra_sql})
            AND (c2.created_at >= '2025-01-01' OR c2.updated_at >= '2025-01-01')
            AND c2.name <> 'prueba'
            AND c2.description <> 'prueba'
            AND c2.name <> 'test'
        ) c
        JOIN users u ON c.user_id = u.id
        WHERE c.rn = 1
        ORDER BY c.created_at DESC
        """

        results = self._execute_query(query)
        df = pd.DataFrame(results)

        logger.info(f"FLOWS obtenidos de BD: {len(df)}")

        if len(df) > 0:
            antes = len(df)
            df = df.drop_duplicates(subset=['video'], keep='first')
            despues = len(df)

            if antes != despues:
                logger.info(f"Duplicados eliminados: {antes - despues}")

            df['city'] = df.apply(lambda row: self._normalize_city(row['creator_city'], row['creator_country']), axis=1)
            df['created_at'] = pd.to_datetime(df['created_at'])
            df['days_since_creation'] = (datetime.now() - df['created_at']).dt.days

        logger.info(f"FLOWS finales: {len(df)}")

        return df

    def _load_interactions(self):
        """
        Carga interacciones de usuarios con videos.
        Combina ratings, saves y matches en una matriz unificada.
        Si no hay interacciones, crea matriz implicita desde views.
        """
        query = """
        SELECT
            user_id,
            model_id as video_id,
            CASE WHEN value > 5 THEN 5 ELSE value END as rating,
            created_at,
            'rating' as interaction_type
        FROM team_feedbacks
        WHERE type = 'ranking_resume'
        AND value > 0
        AND user_id IS NOT NULL
        UNION ALL
        SELECT
            user_id,
            model_id as video_id,
            3.0 as rating,
            created_at,
            'save' as interaction_type
        FROM likes
        WHERE type = 'save'
        AND user_id IS NOT NULL
        UNION ALL
        SELECT
            user_id,
            model_id as video_id,
            4.0 as rating,
            created_at,
            'match' as interaction_type
        FROM matches
        WHERE status = 'accepted'
        AND user_id IS NOT NULL
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)

        if len(df) == 0:
            logger.warning("No hay interacciones directas, creando matriz implicita desde views de resumes")

            query_implicit = """
            SELECT
                r.user_id as creator_id,
                r.id as video_id,
                r.views,
                r.created_at
            FROM resumes r
            WHERE r.status = 'send'
            AND r.views > 0
            AND r.deleted_at IS NULL
            LIMIT 5000
            """
            implicit_results = self._execute_query(query_implicit)
            implicit_df = pd.DataFrame(implicit_results)

            interactions = []
            for _, row in implicit_df.iterrows():
                num_interactions = min(int(row['views']), 50)
                for _ in range(num_interactions):
                    interactions.append({
                        'user_id': None,
                        'video_id': row['video_id'],
                        'rating': 3.0,
                        'created_at': row['created_at'],
                        'interaction_type': 'view_implicit'
                    })

            df = pd.DataFrame(interactions)

        logger.info(f"Interacciones cargadas: {len(df)}")

        if len(df) == 0:
            df = pd.DataFrame(columns=['user_id', 'video_id', 'rating', 'created_at', 'interaction_type'])

        return df

    def _load_connections(self):
        """
        Carga conexiones sociales entre usuarios.
        Solo incluye conexiones con status accepted para el grafo social.
        """
        query = """
        SELECT
            from_id as user_id,
            to_id as connected_user_id,
            status,
            created_at
        FROM user_connections
        WHERE status = 'accepted'
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)
        logger.info(f"Conexiones sociales cargadas: {len(df)}")
        return df

    def get_user_history(self, user_id):
        """
        Obtiene historial de videos vistos por un usuario.
        Retorna set de IDs de videos con los que el usuario ha interactuado.
        """
        if self.interactions_df is None or len(self.interactions_df) == 0:
            return set()

        if 'user_id' not in self.interactions_df.columns:
            return set()

        user_interactions = self.interactions_df[
            self.interactions_df['user_id'] == user_id
        ]
        return set(user_interactions['video_id'].tolist())

    def get_user_network(self, user_id):
        """
        Obtiene red social de un usuario.
        Retorna lista de IDs de usuarios conectados con status accepted.
        """
        if self.connections_df is None or len(self.connections_df) == 0:
            return []

        connections = self.connections_df[
            self.connections_df['user_id'] == user_id
        ]
        return connections['connected_user_id'].tolist()
