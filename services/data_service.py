from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from utils.logger import LoggerConfig
from utils.db_connect import get_db_connection

logger = LoggerConfig.get_logger(__name__)


class DataService:
    """
    Servicio singleton para carga y gestion de datos desde MySQL.

    Carga usuarios, videos, flows, interacciones y conexiones en DataFrames.
    Implementa blacklist de URLs a nivel SQL.
    """

    _instancia: Optional['DataService'] = None
    _inicializado: bool = False

    def __new__(
        cls,
        connection_factory: Optional[Any] = None
    ) -> 'DataService':
        """
        Crea nueva instancia usando patron singleton.

        Args:
            connection_factory: Factory para crear conexiones MySQL

        Returns:
            Instancia unica de DataService
        """
        if cls._instancia is None:
            cls._instancia = super(DataService, cls).__new__(cls)
        return cls._instancia

    def __init__(self, connection_factory: Optional[Any] = None) -> None:
        """
        Inicializa servicio de datos.

        Args:
            connection_factory: Factory para crear conexiones MySQL

        Raises:
            ValueError: Si connection_factory es None en primera inicializacion
        """
        if DataService._inicializado:
            return

        if connection_factory is None:
            raise ValueError(
                "connection_factory requerido en primera inicializacion"
            )

        self.connection_factory = connection_factory
        self.users_df: pd.DataFrame = pd.DataFrame()
        self.videos_df: pd.DataFrame = pd.DataFrame()
        self.interactions_df: pd.DataFrame = pd.DataFrame()
        self.connections_df: pd.DataFrame = pd.DataFrame()
        self.flows_df: pd.DataFrame = pd.DataFrame()
        self._conn: Optional[Any] = None
        self._tunnel: Optional[Any] = None
        self.lista_negra: Set[str] = self._cargar_lista_negra()
        DataService._inicializado = True

    def _cargar_lista_negra(self) -> Set[str]:
        """
        Carga lista de URLs bloqueadas desde data/blacklist.csv.

        Returns:
            Set de URLs a excluir en queries SQL
        """
        lista_negra_path = Path('data/blacklist.csv')
        urls_bloqueadas: Set[str] = set()

        if not lista_negra_path.exists():
            logger.warning("No se encontro data/blacklist.csv")
            return urls_bloqueadas

        try:
            with open(lista_negra_path, 'r', encoding='utf-8') as f:
                lineas = f.readlines()
                for linea in lineas:
                    url = linea.strip()
                    if url and not url.startswith('#'):
                        urls_bloqueadas.add(url)

            logger.info(
                f"Lista negra cargada: {len(urls_bloqueadas)} URLs bloqueadas"
            )
        except Exception as e:
            logger.error(f"Error cargando lista negra: {e}")

        return urls_bloqueadas

    def load_all_data(self) -> None:
        """
        Carga todos los datos desde MySQL a DataFrames en memoria.

        Establece conexion y ejecuta carga de usuarios, videos, flows,
        interacciones y conexiones.

        Raises:
            Exception: Si falla la carga de datos
        """
        logger.info("Iniciando carga de datos")
        self._conn, self._tunnel = get_db_connection()

        try:
            self.users_df = self._load_users()
            self.videos_df = self._load_videos()
            self.interactions_df = self._load_interactions()
            self.connections_df = self._load_connections()
            self.flows_df = self._load_flows()
            logger.info("Carga de datos completada")
        except Exception as e:
            logger.error(f"Error cargando datos: {e}")
            if self._conn:
                self._conn.close()
            if self._tunnel:
                self._tunnel.stop_tunnel()
            raise

    def _execute_query(
        self,
        query: str,
        params: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        Ejecuta query SQL y retorna resultados.

        Args:
            query: Query SQL a ejecutar
            params: Parametros opcionales para query

        Returns:
            Lista de diccionarios con resultados

        Raises:
            RuntimeError: Si no hay conexion establecida
        """
        if not self._conn or not self._conn.connection:
            raise RuntimeError("No hay conexion establecida")

        results = self._conn.execute_query(query, params)
        return results

    def _normalize_city(self, city: str, country: str) -> str:
        """
        Normaliza nombres de ciudades aplicando mapeo estandar.

        Args:
            city: Nombre de la ciudad
            country: Nombre del pais

        Returns:
            Ciudad normalizada o 'Unknown' si no hay datos validos
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

    def _load_users(self) -> pd.DataFrame:
        """
        Carga usuarios desde tabla users con datos de perfiles.

        Incluye skills, languages, tools, knowledge y objetivos.
        Solo usuarios creados o actualizados en ultimos 90 dias.

        Returns:
            DataFrame con datos de usuarios
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
        AND (u.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
             OR u.updated_at >= DATE_SUB(NOW(), INTERVAL 90 DAY))
        """

        results = self._execute_query(query)

        if not results:
            logger.warning("No se encontraron usuarios en BD")
            df_empty = pd.DataFrame(
                columns=[
                    'id', 'name', 'email', 'city', 'country', 'skills',
                    'knowledges', 'tools', 'languages', 'seniority',
                    'model_type', 'opencall_objective'
                ]
            )
            df_empty['city'] = df_empty['city'].astype('category')
            df_empty['country'] = df_empty['country'].astype('category')
            return df_empty

        df = pd.DataFrame(results)

        df['city'] = df['city'].astype('category')
        df['country'] = df['country'].astype('category')

        logger.info(f"Usuarios cargados: {len(df)}")
        return df

    def _load_videos(self) -> pd.DataFrame:
        """
        Carga videos/resumes desde tabla resumes con metricas de engagement.

        Aplica blacklist a nivel SQL y calcula scores normalizados.
        Incluye ratings, connections, likes, exhibited y views.

        Returns:
            DataFrame con datos de videos
        """
        lista_negra_sql = (
            ','.join([f"'{url}'" for url in self.lista_negra])
            if self.lista_negra
            else "''"
        )

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
        AND r.created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY)
        AND LOWER(r.video) NOT LIKE '%prueba%'
        AND LOWER(r.video) NOT LIKE '%test%'
        AND LOWER(COALESCE(r.description, '')) NOT LIKE '%prueba%'
        AND LOWER(COALESCE(r.description, '')) NOT LIKE '%test%'
        """
        results = self._execute_query(query)

        if not results:
            logger.warning("No se encontraron videos/resumes en BD")
            df_empty = pd.DataFrame(
                columns=[
                    'id', 'user_id', 'video', 'views', 'video_skills',
                    'video_knowledges', 'video_tools', 'video_languages',
                    'role_objectives', 'created_at', 'description',
                    'creator_city', 'creator_country', 'creator_name',
                    'avg_rating', 'rating_count', 'has_rating',
                    'connection_count', 'like_count', 'exhibited_count',
                    'actual_views', 'city', 'days_since_creation'
                ]
            )
            df_empty['city'] = df_empty['city'].astype('category')
            df_empty['creator_name'] = df_empty['creator_name'].astype('category')
            return df_empty

        df = pd.DataFrame(results)

        numeric_int_cols = {
            'views': 'actual_views',
            'rating_count': 'rating_count',
            'has_rating': 'has_rating',
            'connection_count': 'connection_count',
            'like_count': 'like_count',
            'exhibited_count': 'exhibited_count'
        }

        for new_col, source_col in numeric_int_cols.items():
            df[new_col] = (
                pd.to_numeric(df[source_col], errors='coerce')
                .fillna(0)
                .astype(int)
            )

        df['avg_rating'] = (
            pd.to_numeric(df['avg_rating'], errors='coerce')
            .fillna(0)
            .astype(float)
        )

        df['city'] = df.apply(
            lambda row: self._normalize_city(
                row['creator_city'],
                row['creator_country']
            ),
            axis=1
        )

        df['created_at'] = pd.to_datetime(df['created_at'])
        df['days_since_creation'] = (
            datetime.now() - df['created_at']
        ).dt.days

        df['city'] = df['city'].astype('category')
        df['creator_name'] = df['creator_name'].astype('category')

        logger.info(f"Videos cargados: {len(df)}")
        logger.info(
            f"Videos con ciudad valida: "
            f"{len(df[df['city'] != 'Unknown'])}"
        )
        logger.info(f"Ciudades unicas: {df['city'].nunique()}")

        return df

    def _load_flows(self) -> pd.DataFrame:
        """
        Carga challenges/flows desde tabla challenges.

        Filtra por status published, aplica blacklist y elimina duplicados.
        Solo incluye flows creados/actualizados en ultimos 90 dias.

        Returns:
            DataFrame con datos de flows
        """
        lista_negra_sql = (
            ','.join([f"'{url}'" for url in self.lista_negra])
            if self.lista_negra
            else "''"
        )

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
                ROW_NUMBER() OVER (
                    PARTITION BY c2.video ORDER BY c2.created_at DESC
                ) as rn
            FROM challenges c2
            WHERE c2.deleted_at IS NULL
            AND c2.status = 'published'
            AND c2.video IS NOT NULL
            AND c2.video NOT IN ({lista_negra_sql})
            AND (c2.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY) OR c2.updated_at >= DATE_SUB(NOW(), INTERVAL 90 DAY))
            AND c2.name <> 'prueba'
            AND c2.description <> 'prueba'
            AND c2.name <> 'test'
        ) c
        JOIN users u ON c.user_id = u.id
        WHERE c.rn = 1
        ORDER BY c.created_at DESC
        """

        results = self._execute_query(query)

        if not results:
            logger.warning("No se encontraron FLOWS en BD")
            df_empty = pd.DataFrame(
                columns=[
                    'id', 'user_id', 'video', 'name', 'description',
                    'created_at', 'creator_name', 'creator_city',
                    'creator_country', 'city', 'days_since_creation'
                ]
            )
            df_empty['city'] = df_empty['city'].astype('category')
            df_empty['creator_name'] = df_empty['creator_name'].astype('category')
            return df_empty

        df = pd.DataFrame(results)
        logger.info(f"FLOWS obtenidos de BD: {len(df)}")

        antes = len(df)
        df = df.drop_duplicates(subset=['video'], keep='first')
        despues = len(df)

        if antes != despues:
            logger.info(f"Duplicados eliminados: {antes - despues}")

        df['city'] = df.apply(
            lambda row: self._normalize_city(
                row['creator_city'],
                row['creator_country']
            ),
            axis=1
        )
        df['created_at'] = pd.to_datetime(df['created_at'])
        df['days_since_creation'] = (
            datetime.now() - df['created_at']
        ).dt.days

        df['city'] = df['city'].astype('category')
        df['creator_name'] = df['creator_name'].astype('category')

        logger.info(f"FLOWS finales: {len(df)}")

        return df

    def _load_interactions(self) -> pd.DataFrame:
        """
        Carga interacciones de usuarios con videos.

        Combina ratings, saves, matches y vistas en matriz unificada.
        Ratings/saves/matches: ultimos 90 dias.
        Vistas (activity_log): ultimos 30 dias.
        Si no hay interacciones, crea matriz implicita desde views.

        Returns:
            DataFrame con interacciones
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
        AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
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
        AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
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
        AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        UNION ALL
        SELECT
            causer_id as user_id,
            subject_id as video_id,
            2.0 as rating,
            created_at,
            'view' as interaction_type
        FROM activity_log
        WHERE description LIKE '%video%view%'
        AND causer_id IS NOT NULL
        AND subject_id IS NOT NULL
        AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)

        if len(df) == 0:
            logger.warning(
                "No hay interacciones directas, "
                "creando matriz implicita desde views"
            )

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
            AND r.created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
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
            df = pd.DataFrame(
                columns=[
                    'user_id', 'video_id', 'rating',
                    'created_at', 'interaction_type'
                ]
            )

        return df

    def _load_connections(self) -> pd.DataFrame:
        """
        Carga conexiones sociales entre usuarios.

        Solo incluye conexiones con status accepted.
        Solo conexiones de ultimos 90 dias.

        Returns:
            DataFrame con conexiones
        """
        query = """
        SELECT
            from_id as user_id,
            to_id as connected_user_id,
            status,
            created_at
        FROM user_connections
        WHERE status = 'accepted'
        AND created_at >= DATE_SUB(NOW(), INTERVAL 90 DAY)
        """
        results = self._execute_query(query)
        df = pd.DataFrame(results)
        logger.info(f"Conexiones sociales cargadas: {len(df)}")
        return df

    def get_user_history(self, user_id: int) -> Set[int]:
        """
        Obtiene historial de videos vistos por usuario.

        Args:
            user_id: ID del usuario

        Returns:
            Set de IDs de videos con los que usuario ha interactuado
        """
        if self.interactions_df is None or len(self.interactions_df) == 0:
            return set()

        if 'user_id' not in self.interactions_df.columns:
            return set()

        user_interactions = self.interactions_df[
            self.interactions_df['user_id'] == user_id
        ]
        return set(user_interactions['video_id'].tolist())

    def get_user_network(self, user_id: int) -> List[int]:
        """
        Obtiene red social de usuario.

        Args:
            user_id: ID del usuario

        Returns:
            Lista de IDs de usuarios conectados con status accepted
        """
        if self.connections_df is None or len(self.connections_df) == 0:
            return []

        connections = self.connections_df[
            self.connections_df['user_id'] == user_id
        ]
        return connections['connected_user_id'].tolist()
