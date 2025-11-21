import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd
from scipy.spatial.distance import cosine

from core.database import MySQLConnection
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)


class BanditContextualAdaptativo:
    """
    Algoritmo de Contextual Bandits con exploracion adaptativa.

    Utiliza LinUCB para balancear exploracion-explotacion en recomendaciones.
    Ajusta parametros dinamicamente segun varianza de recompensas recientes.
    """

    RIDGE_REGULARIZATION: float = 0.001
    MIN_HISTORY_FOR_ADAPTATION: int = 10
    RECENT_REWARDS_WINDOW: int = 50
    MAX_HISTORY_SIZE: int = 1000
    HISTORY_TRIM_SIZE: int = 500

    def __init__(
        self,
        n_features: int,
        alpha: float = 1.0,
        beta: float = 0.5
    ) -> None:
        """
        Inicializa bandit contextual con matrices de Ridge Regression.

        Args:
            n_features: Numero de features contextuales
            alpha: Parametro de exploracion UCB
            beta: Parametro de adaptacion de exploracion
        """
        self.alpha = alpha
        self.beta = beta
        self.n_features = n_features
        self.A = np.identity(n_features)
        self.b = np.zeros(n_features)
        self.theta = np.zeros(n_features)
        self.A_inv = np.identity(n_features)
        self.historial_recompensas: List[float] = []
        self.historial_contextos: List[np.ndarray] = []

    def seleccionar_lote(self, contextos: np.ndarray) -> np.ndarray:
        """
        Selecciona videos usando Upper Confidence Bound en batch.

        Args:
            contextos: Matriz de features contextuales (n_videos, n_features)

        Returns:
            Array de scores UCB para cada video candidato
        """
        self.theta = self.A_inv.dot(self.b)
        recompensas_esperadas = contextos.dot(self.theta)
        incertidumbres = self.alpha * np.sqrt(
            np.sum(contextos.dot(self.A_inv) * contextos, axis=1)
        )
        bonus_exploracion = self._calcular_exploracion_adaptativa(contextos)
        ucb = recompensas_esperadas + incertidumbres + bonus_exploracion
        return ucb

    def _calcular_exploracion_adaptativa(
        self,
        contextos: np.ndarray
    ) -> np.ndarray:
        """
        Calcula bonus de exploracion adaptativo segun varianza de recompensas.

        Args:
            contextos: Matriz de features contextuales

        Returns:
            Array de bonus de exploracion por video
        """
        if len(self.historial_recompensas) < self.MIN_HISTORY_FOR_ADAPTATION:
            return np.full(len(contextos), 0.7)

        recompensas_recientes = (
            self.historial_recompensas[-self.RECENT_REWARDS_WINDOW:]
        )
        varianza_recompensas = np.var(recompensas_recientes)
        factor_exploracion = self.beta * varianza_recompensas * 1.3
        return factor_exploracion * np.random.uniform(0, 1, len(contextos))

    def actualizar(self, contexto: np.ndarray, recompensa: float) -> None:
        """
        Actualiza modelo con feedback de usuario.

        Args:
            contexto: Vector de features contextuales
            recompensa: Recompensa observada
        """
        self.A += np.outer(contexto, contexto)
        self.b += recompensa * contexto
        self.A_inv = np.linalg.inv(
            self.A + self.RIDGE_REGULARIZATION * np.identity(self.n_features)
        )
        self.historial_recompensas.append(recompensa)
        self.historial_contextos.append(contexto)

        if len(self.historial_recompensas) > self.MAX_HISTORY_SIZE:
            self.historial_recompensas = (
                self.historial_recompensas[-self.HISTORY_TRIM_SIZE:]
            )
            self.historial_contextos = (
                self.historial_contextos[-self.HISTORY_TRIM_SIZE:]
            )

    def obtener_estadisticas_rendimiento(self) -> Dict[str, Any]:
        """
        Obtiene metricas de rendimiento del bandit.

        Returns:
            Diccionario con estadisticas de rendimiento
        """
        if len(self.historial_recompensas) == 0:
            return {'recompensa_promedio': 0, 'total_selecciones': 0}

        promedio_reciente = (
            np.mean(self.historial_recompensas[-50:])
            if len(self.historial_recompensas) >= 50
            else np.mean(self.historial_recompensas)
        )

        return {
            'recompensa_promedio': np.mean(self.historial_recompensas),
            'total_selecciones': len(self.historial_recompensas),
            'promedio_reciente': promedio_reciente
        }


class RecommendationEngine:
    """
    Motor de recomendaciones singleton con bandits contextuales.

    Implementa patron mixto VMP-AU-AU-VMP-NU-FW para feed infinito.
    Combina collaborative filtering, content-based y social signals.
    Usa embeddings de skills, grafo social y scores precalculados.
    """

    _instancia: Optional['RecommendationEngine'] = None
    _inicializado: bool = False

    N_FEATURES: int = 18
    PATRON_FEED: List[str] = ['VMP', 'AU', 'AU', 'VMP', 'NU', 'FW']
    VIDEOS_POR_RESPUESTA: int = 24
    VENTANA_DIVERSIDAD_CREADORES: int = 12
    MAX_SKILLS_POR_VIDEO: int = 5
    MAX_KNOWLEDGE_POR_VIDEO: int = 3
    MAX_TOOLS_POR_VIDEO: int = 3
    MAX_LANGUAGES_POR_VIDEO: int = 3

    def __new__(
        cls,
        data_service: Optional[Any] = None
    ) -> 'RecommendationEngine':
        """
        Crea nueva instancia usando patron singleton.

        Args:
            data_service: Servicio de datos

        Returns:
            Instancia unica de RecommendationEngine
        """
        cls._instancia = super(RecommendationEngine, cls).__new__(cls)
        return cls._instancia

    def __init__(self, data_service: Any) -> None:
        """
        Inicializa motor de recomendaciones con datos desde DataService.

        Args:
            data_service: Instancia de DataService con datos cargados
        """
        self.data_service = data_service
        self.videos_df = data_service.videos_df
        self.interactions_df = data_service.interactions_df
        self.flows_df = data_service.flows_df
        self.connections_df = data_service.connections_df
        self.patron = self.PATRON_FEED
        self.longitud_patron = len(self.patron)
        self.videos_por_respuesta = self.VIDEOS_POR_RESPUESTA

        logger.info(f"Inicializando recommender con {len(self.flows_df)} flows")

        self._cachear_datos_videos()
        self._construir_embeddings_skills()
        self._construir_grafo_social()
        self._construir_matrices_lookup()
        self._inicializar_bandits()
        self._precalcular_scores_avanzados()

    def _cachear_datos_videos(self) -> None:
        """
        Construye cache de skills, knowledges, tools y languages por video.

        Extrae y parsea JSON de cada video a sets para lookup O(1).
        Mapea video_id a creator_id y video_url.
        """
        logger.info("Cacheando datos de videos para acceso rapido")

        self.cache_skills_video: Dict[int, Set[str]] = {}
        self.cache_knowledges_video: Dict[int, Set[str]] = {}
        self.cache_tools_video: Dict[int, Set[str]] = {}
        self.cache_languages_video: Dict[int, Set[str]] = {}
        self.video_a_creador: Dict[int, int] = {}
        self.video_a_url: Dict[int, str] = {}

        for idx, row in self.videos_df.iterrows():
            video_id = row['id']

            self.cache_skills_video[video_id] = self._parse_json_to_set(
                row.get('video_skills'),
                self.MAX_SKILLS_POR_VIDEO
            )
            self.cache_knowledges_video[video_id] = self._parse_json_to_set(
                row.get('video_knowledges'),
                self.MAX_KNOWLEDGE_POR_VIDEO
            )
            self.cache_tools_video[video_id] = self._parse_json_to_set(
                row.get('video_tools'),
                self.MAX_TOOLS_POR_VIDEO
            )
            self.cache_languages_video[video_id] = self._parse_json_to_set(
                row.get('video_languages'),
                self.MAX_LANGUAGES_POR_VIDEO
            )

            self.video_a_creador[video_id] = row['user_id']
            self.video_a_url[video_id] = row['video']

        logger.info(f"Datos cacheados para {len(self.cache_skills_video)} videos")

    def _parse_json_to_set(
        self,
        field_value: Any,
        max_items: int
    ) -> Set[str]:
        """
        Parsea campo JSON a set de strings.

        Args:
            field_value: Valor del campo a parsear
            max_items: Numero maximo de items a extraer

        Returns:
            Set de strings parseados
        """
        result: Set[str] = set()
        try:
            if pd.notna(field_value):
                data = (
                    json.loads(field_value)
                    if isinstance(field_value, str)
                    else field_value
                )
                if isinstance(data, list):
                    result = set(data[:max_items])
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.debug(f"Error parsing JSON field: {e}")

        return result

    def _video_en_lista_negra(self, video_id: int) -> bool:
        """
        Verifica si video esta en blacklist de URLs.

        Args:
            video_id: ID del video

        Returns:
            True si URL del video esta bloqueada
        """
        if video_id not in self.video_a_url:
            return False
        video_url = self.video_a_url[video_id]
        return video_url in self.data_service.lista_negra

    def _construir_embeddings_skills(self) -> None:
        """
        Construye embeddings de skills usando matriz de coocurrencia normalizada.

        Calcula frecuencias de skills y relaciones entre ellos.
        Genera skill_a_idx, idx_a_skill y embeddings_skills para similitud.
        """
        logger.info("Construyendo embeddings avanzados de skills")

        todos_skills: Set[str] = set()
        for skills in self.cache_skills_video.values():
            todos_skills.update(skills)

        self.skill_a_idx = {
            skill: idx for idx, skill in enumerate(sorted(todos_skills))
        }
        self.idx_a_skill = {idx: skill for skill, idx in self.skill_a_idx.items()}
        n_skills = len(self.skill_a_idx)

        coocurrencia = np.zeros((n_skills, n_skills))
        conteo_skills: Counter[str] = Counter()

        for skills in self.cache_skills_video.values():
            lista_skills = list(skills)
            for skill in lista_skills:
                if skill in self.skill_a_idx:
                    conteo_skills[skill] += 1

            for i, skill1 in enumerate(lista_skills):
                if skill1 in self.skill_a_idx:
                    idx1 = self.skill_a_idx[skill1]
                    for skill2 in lista_skills[i:]:
                        if skill2 in self.skill_a_idx:
                            idx2 = self.skill_a_idx[skill2]
                            coocurrencia[idx1, idx2] += 1
                            coocurrencia[idx2, idx1] += 1

        sumas_filas = np.sum(coocurrencia, axis=1, keepdims=True)
        sumas_filas[sumas_filas == 0] = 1
        coocurrencia = coocurrencia / sumas_filas

        self.embeddings_skills = coocurrencia
        self.conteo_skills = conteo_skills

        n_videos = len(self.videos_df)
        ids_videos = self.videos_df['id'].tolist()

        matriz_skills = np.zeros((n_videos, n_skills))

        for i, vid_id in enumerate(ids_videos):
            skills = self.cache_skills_video.get(vid_id, set())
            for skill in skills:
                if skill in self.skill_a_idx:
                    matriz_skills[i, self.skill_a_idx[skill]] = 1

        normas = np.linalg.norm(matriz_skills, axis=1, keepdims=True)
        normas[normas == 0] = 1
        matriz_skills_norm = matriz_skills / normas

        self.matriz_skills = matriz_skills_norm
        self.video_id_a_idx = {vid: i for i, vid in enumerate(ids_videos)}

        logger.info(f"Embeddings construidos para {n_skills} skills")

    def _construir_grafo_social(self) -> None:
        """
        Construye grafo de conexiones sociales entre usuarios.

        Calcula scores de influencia basados en numero de conexiones.
        Genera grafo_social y influencia_social para social signals.
        """
        logger.info("Construyendo grafo social con scores de influencia")

        self.grafo_social: Dict[int, Set[int]] = defaultdict(set)
        self.influencia_social: Dict[int, float] = defaultdict(float)

        if self.connections_df is not None and len(self.connections_df) > 0:
            for _, row in self.connections_df.iterrows():
                self.grafo_social[row['user_id']].add(row['connected_user_id'])

            for user_id, conexiones in self.grafo_social.items():
                self.influencia_social[user_id] = np.log1p(len(conexiones)) / 10.0

        logger.info(f"Grafo social construido: {len(self.grafo_social)} usuarios")

    def _construir_matrices_lookup(self) -> None:
        """
        Pre-construye matrices y diccionarios de lookup para procesamiento vectorizado.

        Crea indices rapidos para skills, knowledges, tools y languages.
        Genera matrices binarias por video para calculo batch de similitudes.
        """
        logger.info("Pre-construyendo matrices de lookup para vectorizacion")

        self.all_skills = sorted(set().union(*self.cache_skills_video.values()))
        self.all_knowledges = sorted(
            set().union(*self.cache_knowledges_video.values())
        )
        self.all_tools = sorted(set().union(*self.cache_tools_video.values()))
        self.all_languages = sorted(
            set().union(*self.cache_languages_video.values())
        )

        self.skill_to_idx_fast = {s: i for i, s in enumerate(self.all_skills)}
        self.knowledge_to_idx_fast = {
            k: i for i, k in enumerate(self.all_knowledges)
        }
        self.tool_to_idx_fast = {t: i for i, t in enumerate(self.all_tools)}
        self.language_to_idx_fast = {
            l: i for i, l in enumerate(self.all_languages)
        }

        logger.info("Matrices de lookup construidas")

    def _inicializar_bandits(self) -> None:
        """
        Inicializa bandits contextuales para cada categoria de video.

        VMP, AU, NU con parametros especificos de exploracion.
        Cada bandit aprende independientemente de feedback de usuarios.
        """
        logger.info("Inicializando bandits contextuales adaptativos")

        self.bandit_vmp = BanditContextualAdaptativo(
            self.N_FEATURES,
            alpha=1.5,
            beta=0.8
        )
        self.bandit_au = BanditContextualAdaptativo(
            self.N_FEATURES,
            alpha=1.3,
            beta=0.7
        )
        self.bandit_nu = BanditContextualAdaptativo(
            self.N_FEATURES,
            alpha=1.8,
            beta=0.9
        )

    def _precalcular_scores_avanzados(self) -> None:
        """
        Precalcula multiples scores combinados para cada video.

        Calcula engagement, temporal, calidad, popularidad, diversidad y rareza.
        Normaliza metricas y aplica transformaciones logaritmicas.
        """
        logger.info("Precalculando scores avanzados con gates de calidad")

        df = self.videos_df.copy()

        views_log = np.log1p(df['views'].astype(float))
        views_norm = (
            (views_log - views_log.min()) /
            (views_log.max() - views_log.min() + 1e-6)
        )

        rating_norm = df['avg_rating'].astype(float) / 5.0

        connections_log = np.log1p(df['connection_count'].astype(float))
        connections_norm = (
            (connections_log - connections_log.min()) /
            (connections_log.max() - connections_log.min() + 1e-6)
        )

        df['score_engagement'] = (
            views_norm * 0.35 +
            rating_norm * 0.40 +
            connections_norm * 0.25
        )

        df['score_temporal'] = np.exp(
            -df['days_since_creation'].astype(float) / 28.0
        )

        contenido_ultra_nuevo = df['days_since_creation'] <= 30
        df['boost_nuevo'] = 1.0
        df.loc[contenido_ultra_nuevo, 'boost_nuevo'] = 1.5

        peso_rating = (
            df['rating_count'].astype(float) /
            (df['rating_count'].astype(float) + 10)
        )
        df['score_calidad'] = (
            df['avg_rating'].astype(float) * peso_rating * 0.7 +
            np.log1p(df['connection_count'].astype(float)) * 0.3
        )

        df['score_popularidad'] = (
            np.log1p(df['views'].astype(float)) * 0.40 +
            df['avg_rating'].astype(float) * 0.35 +
            np.log1p(df['connection_count'].astype(float)) * 0.25
        )

        scores_diversidad_skills = []
        scores_rareza_skills = []
        for vid_id in df['id']:
            skills = self.cache_skills_video.get(vid_id, set())
            knowledges = self.cache_knowledges_video.get(vid_id, set())
            tools = self.cache_tools_video.get(vid_id, set())

            total_atributos = len(skills) + len(knowledges) + len(tools)
            scores_diversidad_skills.append(total_atributos / 15.0)

            if skills:
                rarezas = [
                    1.0 / (self.conteo_skills.get(s, 1) + 1) for s in skills
                ]
                scores_rareza_skills.append(np.mean(rarezas) * 100)
            else:
                scores_rareza_skills.append(0)

        df['diversidad_skills'] = scores_diversidad_skills
        df['rareza_skills'] = scores_rareza_skills

        es_contenido_nuevo = df['days_since_creation'] < 14
        gate_calidad = (
            (df['avg_rating'] >= 3.0) |
            (df['views'] >= 20) |
            (df['connection_count'] >= 2) |
            (df['rating_count'] >= 2) |
            es_contenido_nuevo
        )
        df['pasa_gate_calidad'] = gate_calidad.astype(int)

        self.videos_df = df

        logger.info(
            "Scores avanzados precalculados con filtros de calidad estrictos"
        )

    def _obtener_preferencias_usuario_rapido(
        self,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Extrae preferencias de usuario desde interacciones pasadas.

        Args:
            user_id: ID del usuario

        Returns:
            Diccionario con preferencias agregadas y ponderadas
        """
        prefs: Dict[str, Any] = {
            'skills': set(),
            'knowledges': set(),
            'tools': set(),
            'languages': set(),
            'cities': set(),
            'vistos': set(),
            'vector_skills': None,
            'pesos_skills': {},
            'red_social': set(),
            'score_influencia_social': 0
        }

        if (len(self.interactions_df) == 0 or
                'user_id' not in self.interactions_df.columns):
            return prefs

        interacciones_usuario = self.interactions_df[
            self.interactions_df['user_id'] == user_id
        ]

        if len(interacciones_usuario) == 0:
            return prefs

        prefs['vistos'] = set(interacciones_usuario['video_id'].tolist())
        prefs['red_social'] = self.grafo_social.get(user_id, set())
        prefs['score_influencia_social'] = self.influencia_social.get(user_id, 0)

        muestra_vistos = list(prefs['vistos'])[:80]

        contador_skills: Counter[str] = Counter()
        for vid_id in muestra_vistos:
            if vid_id in self.cache_skills_video:
                skills = self.cache_skills_video[vid_id]
                prefs['skills'].update(skills)
                for skill in skills:
                    contador_skills[skill] += 1

            if vid_id in self.cache_knowledges_video:
                prefs['knowledges'].update(self.cache_knowledges_video[vid_id])

            if vid_id in self.cache_tools_video:
                prefs['tools'].update(self.cache_tools_video[vid_id])

            if vid_id in self.cache_languages_video:
                prefs['languages'].update(self.cache_languages_video[vid_id])

        if contador_skills:
            total_conteo = sum(contador_skills.values())
            prefs['pesos_skills'] = {
                s: c/total_conteo for s, c in contador_skills.items()
            }

        if prefs['skills'] and self.skill_a_idx:
            vector_skills = np.zeros(len(self.skill_a_idx))
            for skill, conteo in contador_skills.items():
                if skill in self.skill_a_idx:
                    vector_skills[self.skill_a_idx[skill]] = conteo
            norma = np.linalg.norm(vector_skills)
            if norma > 0:
                vector_skills = vector_skills / norma
            prefs['vector_skills'] = vector_skills

        videos_vistos = self.videos_df[self.videos_df['id'].isin(muestra_vistos)]
        ciudades = videos_vistos[videos_vistos['city'].notna()]['city'].unique()
        prefs['cities'] = set(ciudades)

        return prefs

    def _calcular_similitudes_skills_lote(
        self,
        ids_videos: List[int],
        prefs_usuario: Dict[str, Any]
    ) -> np.ndarray:
        """
        Calcula similitud coseno entre skills de usuario y videos en batch.

        Args:
            ids_videos: Lista de IDs de videos
            prefs_usuario: Preferencias del usuario

        Returns:
            Array de similitudes normalizadas entre 0 y 1
        """
        if prefs_usuario['vector_skills'] is None:
            return np.full(len(ids_videos), 0.5)

        similitudes = []
        for vid_id in ids_videos:
            if vid_id in self.video_id_a_idx:
                idx_vid = self.video_id_a_idx[vid_id]
                vector_video = self.matriz_skills[idx_vid]
                if np.linalg.norm(vector_video) > 0:
                    sim = 1 - cosine(prefs_usuario['vector_skills'], vector_video)

                    skills_vid = self.cache_skills_video.get(vid_id, set())
                    solapamiento_ponderado = sum(
                        prefs_usuario['pesos_skills'].get(s, 0)
                        for s in skills_vid
                    )

                    sim_combinada = sim * 0.6 + solapamiento_ponderado * 0.4
                    similitudes.append(max(0, min(1, sim_combinada)))
                else:
                    similitudes.append(0.3)
            else:
                similitudes.append(0.3)

        return np.array(similitudes)

    def _calcular_match_extendido_vectorizado(
        self,
        ids_videos: List[int],
        prefs_usuario: Dict[str, Any]
    ) -> np.ndarray:
        """
        Calcula match score entre preferencias de usuario y atributos de videos.

        Args:
            ids_videos: Lista de IDs de videos
            prefs_usuario: Preferencias del usuario

        Returns:
            Array de scores de match normalizados
        """
        n_videos = len(ids_videos)

        user_skills_set = prefs_usuario['skills']
        user_knowledges_set = prefs_usuario['knowledges']
        user_tools_set = prefs_usuario['tools']
        user_languages_set = prefs_usuario['languages']

        scores = np.zeros(n_videos)

        for i, vid_id in enumerate(ids_videos):
            score = 0

            skills_vid = self.cache_skills_video.get(vid_id, set())
            if skills_vid & user_skills_set:
                score += len(skills_vid & user_skills_set) * 15

            knowledges_vid = self.cache_knowledges_video.get(vid_id, set())
            if knowledges_vid & user_knowledges_set:
                score += len(knowledges_vid & user_knowledges_set) * 12

            tools_vid = self.cache_tools_video.get(vid_id, set())
            if tools_vid & user_tools_set:
                score += len(tools_vid & user_tools_set) * 10

            languages_vid = self.cache_languages_video.get(vid_id, set())
            if languages_vid & user_languages_set:
                score += len(languages_vid & user_languages_set) * 8

            scores[i] = min(score, 100)

        return scores

    def _extraer_features_contexto_vectorizado(
        self,
        df_candidatos: pd.DataFrame,
        prefs_usuario: Dict[str, Any]
    ) -> np.ndarray:
        """
        Extrae features contextuales para cada video candidato.

        Args:
            df_candidatos: DataFrame con videos candidatos
            prefs_usuario: Preferencias del usuario

        Returns:
            Matriz numpy (n_videos, N_FEATURES) normalizada para bandits
        """
        n_candidatos = len(df_candidatos)
        features = np.zeros((n_candidatos, self.N_FEATURES))

        features[:, 0] = df_candidatos['score_engagement'].values
        features[:, 1] = (
            df_candidatos['score_temporal'].values *
            df_candidatos['boost_nuevo'].values
        )
        features[:, 2] = df_candidatos['score_calidad'].values
        features[:, 3] = df_candidatos['score_popularidad'].values
        features[:, 4] = df_candidatos['diversidad_skills'].values

        ids_videos = df_candidatos['id'].tolist()
        features[:, 5] = self._calcular_similitudes_skills_lote(
            ids_videos,
            prefs_usuario
        )

        features[:, 6] = (
            self._calcular_match_extendido_vectorizado(ids_videos, prefs_usuario) /
            100.0
        )

        coincidencias_ciudad = (
            df_candidatos['city'].isin(prefs_usuario['cities']).astype(float).values
        )
        features[:, 7] = coincidencias_ciudad

        coincidencias_sociales = (
            df_candidatos['user_id']
            .isin(prefs_usuario['red_social'])
            .astype(float)
            .values
        )
        features[:, 8] = coincidencias_sociales

        features[:, 9] = np.log1p(df_candidatos['views'].values) / 10.0
        features[:, 10] = df_candidatos['avg_rating'].values / 5.0

        features[:, 11] = df_candidatos['rareza_skills'].values / 100.0

        features[:, 12] = df_candidatos['pasa_gate_calidad'].values

        features[:, 13] = prefs_usuario['score_influencia_social']

        features[:, 14] = (
            df_candidatos['rating_count'].values /
            (df_candidatos['rating_count'].values.max() + 1)
        )

        features[:, 15] = (
            df_candidatos['like_count'].values /
            (df_candidatos['like_count'].values.max() + 1)
        )

        features[:, 16] = (
            df_candidatos['exhibited_count'].values /
            (df_candidatos['exhibited_count'].values.max() + 1)
        )

        features[:, 17] = np.random.uniform(0, 0.3, n_candidatos)

        return features

    def _seleccionar_vmp_rapido(
        self,
        ids_excluir: Set[int],
        prefs_usuario: Dict[str, Any],
        creadores_usados: Set[int],
        n: int = 110
    ) -> List[int]:
        """
        Selecciona videos VMP usando bandit contextual.

        Args:
            ids_excluir: Set de IDs de videos a excluir
            prefs_usuario: Preferencias del usuario
            creadores_usados: Set de IDs de creadores ya usados
            n: Numero de videos a seleccionar

        Returns:
            Lista de video IDs seleccionados
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados)) &
            (self.videos_df['pasa_gate_calidad'] == 1)
        ].copy()

        if len(candidatos) == 0:
            candidatos = self.videos_df[
                (~self.videos_df['id'].isin(ids_excluir)) &
                (~self.videos_df['user_id'].isin(creadores_usados))
            ].copy()

        if len(candidatos) == 0:
            return []

        features = self._extraer_features_contexto_vectorizado(
            candidatos,
            prefs_usuario
        )

        scores_ucb = self.bandit_vmp.seleccionar_lote(features)

        candidatos['score_vmp'] = scores_ucb
        candidatos['score_vmp'] += candidatos['score_engagement'] * 2.2
        candidatos['score_vmp'] += candidatos['score_popularidad'] * 1.6
        candidatos['score_vmp'] += candidatos['score_calidad'] * 1.8

        mascara_nuevo_contenido = candidatos['days_since_creation'] <= 45
        candidatos.loc[mascara_nuevo_contenido, 'score_vmp'] += 1.4

        top_candidatos = candidatos.nlargest(
            min(n*2, len(candidatos)),
            'score_vmp'
        )

        tamanio_muestra = min(n, len(top_candidatos))
        pesos_arr = top_candidatos['score_vmp'].values
        pesos_arr = np.clip(pesos_arr, 0, None)
        suma_pesos = pesos_arr.sum()
        if suma_pesos > 0:
            pesos_arr = pesos_arr / suma_pesos
        else:
            pesos_arr = np.ones(len(pesos_arr)) / len(pesos_arr)

        indices_seleccionados = np.random.choice(
            len(top_candidatos),
            size=tamanio_muestra,
            replace=False,
            p=pesos_arr
        )

        return top_candidatos.iloc[indices_seleccionados]['id'].tolist()

    def _seleccionar_nu_rapido(
        self,
        ids_excluir: Set[int],
        prefs_usuario: Dict[str, Any],
        creadores_usados: Set[int],
        n: int = 95
    ) -> List[int]:
        """
        Selecciona videos NU usando bandit contextual.

        Args:
            ids_excluir: Set de IDs de videos a excluir
            prefs_usuario: Preferencias del usuario
            creadores_usados: Set de IDs de creadores ya usados
            n: Numero de videos a seleccionar

        Returns:
            Lista de video IDs seleccionados
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados)) &
            (self.videos_df['days_since_creation'] <= 45)
        ].copy()

        if len(candidatos) == 0:
            return []

        features = self._extraer_features_contexto_vectorizado(
            candidatos,
            prefs_usuario
        )

        scores_ucb = self.bandit_nu.seleccionar_lote(features)

        candidatos['score_nu'] = scores_ucb
        candidatos['score_nu'] += candidatos['score_temporal'] * 2.5
        candidatos['score_nu'] += candidatos['diversidad_skills'] * 1.8
        candidatos['score_nu'] += candidatos['rareza_skills'] / 100.0 * 1.4
        candidatos['score_nu'] += candidatos['boost_nuevo'] * 0.8
        candidatos['score_nu'] += np.random.uniform(0, 0.6, len(candidatos))

        top_candidatos = candidatos.nlargest(
            min(n*2, len(candidatos)),
            'score_nu'
        )

        if len(top_candidatos) > n:
            return top_candidatos.sample(n=n)['id'].tolist()

        return top_candidatos['id'].tolist()

    def _seleccionar_au_rapido(
        self,
        ids_excluir: Set[int],
        prefs_usuario: Dict[str, Any],
        creadores_usados: Set[int],
        n: int = 170
    ) -> List[int]:
        """
        Selecciona videos AU usando bandit contextual.

        Args:
            ids_excluir: Set de IDs de videos a excluir
            prefs_usuario: Preferencias del usuario
            creadores_usados: Set de IDs de creadores ya usados
            n: Numero de videos a seleccionar

        Returns:
            Lista de video IDs seleccionados
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados))
        ].copy()

        if len(candidatos) == 0:
            return []

        features = self._extraer_features_contexto_vectorizado(
            candidatos,
            prefs_usuario
        )

        scores_ucb = self.bandit_au.seleccionar_lote(features)

        candidatos['score_au'] = scores_ucb
        candidatos['score_au'] += features[:, 5] * 3.5
        candidatos['score_au'] += features[:, 6] * 3.0
        candidatos['score_au'] += candidatos['score_popularidad'] * 1.1
        candidatos['score_au'] += candidatos['score_calidad'] * 1.4
        candidatos['score_au'] += candidatos['score_temporal'] * 0.9
        candidatos['score_au'] += candidatos['rareza_skills'] / 100.0 * 0.9

        mascara_nuevo_contenido = candidatos['days_since_creation'] <= 45
        candidatos.loc[mascara_nuevo_contenido, 'score_au'] += 0.9

        top_candidatos = candidatos.nlargest(
            min(n, len(candidatos)),
            'score_au'
        )

        return top_candidatos['id'].tolist()

    def _seleccionar_flows(
        self,
        ids_excluir: Set[int],
        creadores_usados: Set[int],
        n: int = 40
    ) -> List[int]:
        """
        Selecciona challenges/flows para categoria FW.

        Args:
            ids_excluir: Set de IDs de flows a excluir
            creadores_usados: Set de IDs de creadores ya usados
            n: Numero de flows a seleccionar

        Returns:
            Lista de flow IDs seleccionados
        """
        if self.flows_df is None or len(self.flows_df) == 0:
            return []

        candidatos = self.flows_df[
            (~self.flows_df['id'].isin(ids_excluir)) &
            (~self.flows_df['user_id'].isin(creadores_usados))
        ].copy()

        if len(candidatos) == 0:
            return []

        candidatos['score_flow'] = (
            np.random.uniform(0, 40, len(candidatos)) +
            (60 - candidatos['days_since_creation'].astype(float).values) / 60 * 60
        )

        top_flows = candidatos.nlargest(min(n, len(candidatos)), 'score_flow')
        return top_flows['id'].tolist()

    def _seleccionar_boost_exploracion(
        self,
        ids_excluir: Set[int],
        creadores_usados: Set[int],
        n: int = 75
    ) -> List[int]:
        """
        Selecciona videos aleatorios para boost de exploracion.

        Args:
            ids_excluir: Set de IDs de videos a excluir
            creadores_usados: Set de IDs de creadores ya usados
            n: Numero de videos a seleccionar

        Returns:
            Lista de video IDs seleccionados aleatoriamente
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados))
        ]

        if len(candidatos) == 0:
            return []

        tamanio_muestra = min(n, len(candidatos))
        return candidatos.sample(n=tamanio_muestra)['id'].tolist()

    def generar_scroll_infinito(
        self,
        user_id: int,
        n_videos: int = 24,
        videos_excluidos: Optional[List[int]] = None,
        incluir_fw: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Genera feed infinito mezclando videos y flows segun patron.

        Args:
            user_id: ID del usuario
            n_videos: Numero de videos a generar (siempre 24)
            videos_excluidos: Lista de IDs de videos a excluir
            incluir_fw: Si incluir flows en el feed

        Returns:
            Tupla con lista de videos y metricas de rendimiento
        """
        n_videos = self.videos_por_respuesta
        tiempo_inicio = time.time()

        logger.info(f"Generando scroll infinito para usuario {user_id}")

        prefs_usuario = self._obtener_preferencias_usuario_rapido(user_id)

        ids_excluir = prefs_usuario['vistos'].copy()
        if videos_excluidos:
            videos_excluidos_set = (
                set(videos_excluidos)
                if not isinstance(videos_excluidos, set)
                else videos_excluidos
            )
            ids_excluir.update(videos_excluidos_set)
            logger.info(f"Videos excluidos por historial: {len(videos_excluidos)}")

        creadores_usados: Set[int] = set()

        pool_vmp = self._seleccionar_vmp_rapido(
            ids_excluir,
            prefs_usuario,
            creadores_usados,
            n=110
        )
        pool_nu = self._seleccionar_nu_rapido(
            ids_excluir,
            prefs_usuario,
            creadores_usados,
            n=95
        )
        excluir_para_au = ids_excluir | set(pool_vmp) | set(pool_nu)
        pool_au = self._seleccionar_au_rapido(
            excluir_para_au,
            prefs_usuario,
            creadores_usados,
            n=170
        )
        if incluir_fw:
            pool_flows = self._seleccionar_flows(
                ids_excluir,
                creadores_usados,
                n=40
            )
        else:
            pool_flows = []
        pool_exploracion = self._seleccionar_boost_exploracion(
            excluir_para_au | set(pool_au),
            creadores_usados,
            n=75
        )

        logger.info(
            f"Pools generados - VMP: {len(pool_vmp)}, NU: {len(pool_nu)}, "
            f"AU: {len(pool_au)}, FLOWS: {len(pool_flows)}, "
            f"EXPLORE: {len(pool_exploracion)}"
        )

        feed: List[Dict[str, Any]] = []
        ids_usados: Set[int] = set()
        skills_usados: Set[str] = set()
        creadores_usados_en_feed: Set[int] = set()
        creadores_por_ventana: List[int] = []

        idx_vmp = 0
        idx_nu = 0
        idx_au = 0
        idx_flow = 0
        idx_explore = 0

        ciclos = (n_videos // self.longitud_patron) + 1

        for ciclo in range(ciclos):
            for pos_patron in range(self.longitud_patron):
                if len(feed) >= n_videos:
                    break

                if len(feed) > 0 and len(feed) % self.VENTANA_DIVERSIDAD_CREADORES == 0:
                    if len(creadores_por_ventana) >= self.VENTANA_DIVERSIDAD_CREADORES:
                        creadores_a_remover = (
                            creadores_por_ventana[:self.VENTANA_DIVERSIDAD_CREADORES]
                        )
                        creadores_usados_en_feed = set([
                            c for c in creadores_usados_en_feed
                            if c not in creadores_a_remover
                        ])
                        creadores_por_ventana = (
                            creadores_por_ventana[self.VENTANA_DIVERSIDAD_CREADORES:]
                        )

                tipo_slot = self.patron[pos_patron]
                video_id: Optional[int] = None
                intentos = 0
                max_intentos = 150
                es_flow = False

                if tipo_slot == 'FW':
                    video_encontrado = False
                    while idx_flow < len(pool_flows) and not video_encontrado:
                        vid = pool_flows[idx_flow]
                        idx_flow += 1

                        if vid in ids_usados:
                            continue

                        flow_row = self.flows_df[self.flows_df['id'] == vid]
                        if len(flow_row) == 0:
                            continue

                        creador_flow = flow_row.iloc[0]['user_id']
                        if creador_flow in creadores_usados_en_feed:
                            continue

                        video_id = vid
                        creadores_usados_en_feed.add(creador_flow)
                        creadores_por_ventana.append(creador_flow)
                        es_flow = True
                        video_encontrado = True

                elif tipo_slot == 'VMP':
                    while idx_vmp < len(pool_vmp) and intentos < max_intentos:
                        vid = pool_vmp[idx_vmp]
                        idx_vmp += 1
                        intentos += 1

                        if vid not in ids_usados:
                            creador_vid = self.video_a_creador.get(vid)
                            if (creador_vid is not None and
                                    creador_vid not in creadores_usados_en_feed):
                                skills_vid = self.cache_skills_video.get(vid, set())
                                skills_nuevos = skills_vid - skills_usados
                                if len(skills_nuevos) >= 1 or len(skills_usados) < 3:
                                    video_id = vid
                                    skills_usados.update(skills_vid)
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                    if not video_id and idx_explore < len(pool_exploracion):
                        while idx_explore < len(pool_exploracion):
                            vid = pool_exploracion[idx_explore]
                            idx_explore += 1

                            if vid not in ids_usados:
                                creador_vid = self.video_a_creador.get(vid)
                                if (creador_vid is not None and
                                        creador_vid not in creadores_usados_en_feed):
                                    video_id = vid
                                    skills_usados.update(
                                        self.cache_skills_video.get(vid, set())
                                    )
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                elif tipo_slot == 'AU':
                    while idx_au < len(pool_au) and intentos < max_intentos:
                        vid = pool_au[idx_au]
                        idx_au += 1
                        intentos += 1

                        if self._video_en_lista_negra(vid):
                            continue

                        if vid not in ids_usados:
                            creador_vid = self.video_a_creador.get(vid)
                            if (creador_vid is not None and
                                    creador_vid not in creadores_usados_en_feed):
                                skills_vid = self.cache_skills_video.get(vid, set())
                                skills_nuevos = skills_vid - skills_usados
                                if len(skills_nuevos) >= 1 or len(skills_usados) < 3:
                                    video_id = vid
                                    skills_usados.update(skills_vid)
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                    if not video_id and idx_explore < len(pool_exploracion):
                        while idx_explore < len(pool_exploracion):
                            vid = pool_exploracion[idx_explore]
                            idx_explore += 1

                            if vid not in ids_usados:
                                creador_vid = self.video_a_creador.get(vid)
                                if (creador_vid is not None and
                                        creador_vid not in creadores_usados_en_feed):
                                    video_id = vid
                                    skills_usados.update(
                                        self.cache_skills_video.get(vid, set())
                                    )
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                elif tipo_slot == 'NU':
                    while idx_nu < len(pool_nu) and intentos < max_intentos:
                        vid = pool_nu[idx_nu]
                        idx_nu += 1
                        intentos += 1

                        if self._video_en_lista_negra(vid):
                            continue

                        if vid not in ids_usados:
                            creador_vid = self.video_a_creador.get(vid)
                            if (creador_vid is not None and
                                    creador_vid not in creadores_usados_en_feed):
                                skills_vid = self.cache_skills_video.get(vid, set())
                                skills_nuevos = skills_vid - skills_usados
                                if len(skills_nuevos) >= 1 or len(skills_usados) < 3:
                                    video_id = vid
                                    skills_usados.update(skills_vid)
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                    if not video_id and idx_explore < len(pool_exploracion):
                        while idx_explore < len(pool_exploracion):
                            vid = pool_exploracion[idx_explore]
                            idx_explore += 1

                            if vid not in ids_usados:
                                creador_vid = self.video_a_creador.get(vid)
                                if (creador_vid is not None and
                                        creador_vid not in creadores_usados_en_feed):
                                    video_id = vid
                                    skills_usados.update(
                                        self.cache_skills_video.get(vid, set())
                                    )
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                if video_id:
                    if es_flow:
                        datos_flow = self.flows_df[
                            self.flows_df['id'] == video_id
                        ].iloc[0]
                        feed.append({
                            'position': len(feed) + 1,
                            'video_id': int(video_id),
                            'type': 'challenge',
                            'patron_type': tipo_slot,
                            'video_url': datos_flow['video'],
                            'creator_name': datos_flow.get('creator_name', ''),
                            'city': datos_flow.get('city', ''),
                            'title': datos_flow.get('name', ''),
                            'description': str(datos_flow.get('description', ''))[:100],
                            'talent_type': datos_flow.get('talent_type', ''),
                            'days_old': int(float(datos_flow['days_since_creation'])),
                            'views': 0,
                            'rating': 0.0
                        })
                    else:
                        datos_video = self.videos_df[
                            self.videos_df['id'] == video_id
                        ].iloc[0]
                        feed.append({
                            'position': len(feed) + 1,
                            'video_id': int(video_id),
                            'type': 'resume',
                            'patron_type': tipo_slot,
                            'video_url': datos_video['video'],
                            'creator_name': datos_video.get('creator_name', ''),
                            'city': datos_video.get('city', ''),
                            'views': int(float(datos_video['views'])),
                            'rating': float(datos_video['avg_rating']),
                            'days_old': int(float(datos_video['days_since_creation']))
                        })

                    ids_usados.add(video_id)

        tiempo_exec = time.time() - tiempo_inicio

        conteos_tipo = Counter([item['type'] for item in feed])

        catalogo_total = len(self.videos_df)
        catalogo_disponible = catalogo_total - len(prefs_usuario['vistos'])
        if videos_excluidos:
            catalogo_disponible = catalogo_disponible - len(
                videos_excluidos_set - prefs_usuario['vistos']
            )

        todos_pools = (
            set(pool_vmp) | set(pool_nu) | set(pool_au) |
            set(pool_flows) | set(pool_exploracion)
        )
        cobertura_catalogo = len(todos_pools) / max(catalogo_disponible, 1) * 100

        cobertura_feed = len(ids_usados) / max(n_videos, 1) * 100

        conteo_contenido_nuevo = sum(1 for item in feed if item['days_old'] <= 45)
        ratio_contenido_nuevo = (
            conteo_contenido_nuevo / len(feed) * 100 if len(feed) > 0 else 0
        )

        skills_diversos: Set[str] = set()
        creadores_diversos: Set[int] = set()
        for item in feed:
            video_id_item = item['video_id']
            if video_id_item in self.cache_skills_video:
                skills_diversos.update(self.cache_skills_video[video_id_item])
            if item['type'] != 'FW':
                datos_video = self.videos_df[
                    self.videos_df['id'] == video_id_item
                ]
                if len(datos_video) > 0:
                    creadores_diversos.add(datos_video.iloc[0]['user_id'])

        diversidad_skills = len(skills_diversos) / max(len(feed) * 2, 1) * 100
        diversidad_creadores = (
            len(creadores_usados_en_feed) / max(len(feed), 1) * 100
        )

        avg_views = (
            float(np.mean([item['views'] for item in feed if item['type'] != 'FW']))
            if any(item['type'] != 'FW' for item in feed)
            else 0
        )

        avg_rating = (
            float(np.mean([item['rating'] for item in feed if item['type'] != 'FW']))
            if any(item['type'] != 'FW' for item in feed)
            else 0
        )

        metricas = {
            'total_videos': len(feed),
            'type_distribution': dict(conteos_tipo),
            'unique_creators': len(creadores_usados_en_feed),
            'avg_views': avg_views,
            'avg_rating': avg_rating,
            'execution_time': round(tiempo_exec, 3),
            'catalog_coverage': round(cobertura_catalogo, 2),
            'feed_coverage': round(cobertura_feed, 2),
            'new_content_ratio': round(ratio_contenido_nuevo, 2),
            'skill_diversity': round(diversidad_skills, 2),
            'creator_diversity': round(diversidad_creadores, 2),
            'total_catalog': catalogo_total,
            'available_catalog': catalogo_disponible,
            'pool_sizes': {
                'vmp': len(pool_vmp),
                'nu': len(pool_nu),
                'au': len(pool_au),
                'flows': len(pool_flows),
                'explore': len(pool_exploracion)
            },
            'bandit_stats': {
                'vmp': self.bandit_vmp.obtener_estadisticas_rendimiento(),
                'au': self.bandit_au.obtener_estadisticas_rendimiento(),
                'nu': self.bandit_nu.obtener_estadisticas_rendimiento()
            }
        }

        logger.info(f"Feed generado: {metricas}")

        return feed, metricas

    def _obtener_flows_vistos_usuario(self, user_id: int) -> Set[int]:
        """
        Consulta activity_log para obtener flows ya vistos por usuario.

        Args:
            user_id: ID del usuario

        Returns:
            Set de flow IDs que usuario ya vio
        """
        try:
            conn = MySQLConnection()
            conn.connect()

            query = """
                SELECT DISTINCT subject_id
                FROM activity_log
                WHERE causer_id = %s
                  AND log_name LIKE '%flow%'
                  AND subject_id IS NOT NULL
            """

            result = conn.execute_query(query, (user_id,))
            flows_vistos = set([
                int(row['subject_id'])
                for row in result
                if row['subject_id']
            ])

            conn.close()
            logger.info(f"Usuario {user_id} ha visto {len(flows_vistos)} flows")
            return flows_vistos

        except Exception as e:
            logger.error(f"Error obteniendo flows vistos usuario {user_id}: {e}")
            return set()

    def _seleccionar_flows_para_usuario(
        self,
        user_id: int,
        n: int = 24,
        excluded_ids: Optional[List[int]] = None
    ) -> List[int]:
        """
        Selecciona flows ordenados por relevancia para usuario.

        Args:
            user_id: ID del usuario
            n: Numero de flows a seleccionar
            excluded_ids: Lista de IDs de flows a excluir

        Returns:
            Lista de flow IDs seleccionados
        """
        if excluded_ids is None:
            excluded_ids = []

        if self.flows_df is None or len(self.flows_df) == 0:
            return []

        flows_vistos = self._obtener_flows_vistos_usuario(user_id)

        flows_a_excluir = flows_vistos.union(set(excluded_ids))

        candidatos = self.flows_df[
            (~self.flows_df['id'].isin(flows_a_excluir)) &
            (~self.flows_df['video'].isin(self.data_service.lista_negra))
        ].copy()

        if len(candidatos) == 0:
            candidatos = self.flows_df[
                ~self.flows_df['video'].isin(self.data_service.lista_negra)
            ].copy()
            logger.info(f"Usuario {user_id} agoto todos los flows, reiniciando")

        if len(candidatos) == 0:
            return []

        prefs_usuario = self._obtener_preferencias_usuario_rapido(user_id)

        candidatos['score_relevancia'] = 0.0

        for idx, row in candidatos.iterrows():
            score = 0

            days_old = float(row['days_since_creation'])
            score += max(0, (90 - days_old) / 90 * 30)

            flow_creator = row['user_id']
            if flow_creator in prefs_usuario.get('conexiones', set()):
                score += 30
            else:
                score += np.random.uniform(0, 20)

            candidatos.at[idx, 'score_relevancia'] = score

        top_flows = candidatos.nlargest(min(n, len(candidatos)), 'score_relevancia')
        flow_ids = top_flows['id'].tolist()

        logger.info(f"Seleccionados {len(flow_ids)} flows para usuario {user_id}")
        return flow_ids

    def generar_feed_flows_only(
        self,
        user_id: int,
        n_flows: int = 24,
        excluded_ids: Optional[List[int]] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Genera feed de SOLO flows para endpoint be_discover.

        Args:
            user_id: ID del usuario
            n_flows: Numero de flows a generar
            excluded_ids: Lista de IDs de flows a excluir

        Returns:
            Tupla con lista de flows y metricas de rendimiento
        """
        if excluded_ids is None:
            excluded_ids = []

        tiempo_inicio = time.time()

        logger.info(
            f"Generando feed flows_only para usuario {user_id}, "
            f"excluyendo {len(excluded_ids)} flows"
        )

        flow_ids = self._seleccionar_flows_para_usuario(
            user_id,
            n=n_flows,
            excluded_ids=excluded_ids
        )

        feed: List[Dict[str, Any]] = []
        for idx, flow_id in enumerate(flow_ids):
            flow_row = self.flows_df[self.flows_df['id'] == flow_id]
            if len(flow_row) == 0:
                continue

            datos_flow = flow_row.iloc[0]
            feed.append({
                'position': idx + 1,
                'video_id': int(flow_id),
                'type': 'challenge',
                'patron_type': 'FW',
                'flow_data': datos_flow
            })

        tiempo_exec = time.time() - tiempo_inicio

        metricas = {
            'total_flows': len(feed),
            'execution_time': round(tiempo_exec, 3)
        }

        logger.info(
            f"Feed flows_only generado: {len(feed)} flows en {tiempo_exec:.3f}s"
        )

        return feed, metricas
