import sys
from pathlib import Path
import time
import json
import numpy as np
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime
from scipy.spatial.distance import cosine
from core.database import MySQLConnection
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

class BanditContextualAdaptativo:
    """
    Implementacion de algoritmo de Contextual Bandits con exploracion adaptativa.
    Utiliza LinUCB para balancear exploracion-explotacion en recomendaciones.
    Ajusta parametros dinamicamente segun varianza de recompensas recientes.
    """

    def __init__(self, n_features, alpha=1.0, beta=0.5):
        """
        Inicializa el bandit contextual con matrices de Ridge Regression.
        Configura parametros alpha (exploracion) y beta (adaptacion).
        """
        self.alpha = alpha
        self.beta = beta
        self.n_features = n_features
        self.A = np.identity(n_features)
        self.b = np.zeros(n_features)
        self.theta = np.zeros(n_features)
        self.A_inv = np.identity(n_features)
        self.historial_recompensas = []
        self.historial_contextos = []

    def seleccionar_lote(self, contextos):
        """
        Selecciona videos usando Upper Confidence Bound (UCB) en batch.
        Calcula recompensas esperadas + incertidumbre + exploracion adaptativa.
        Retorna array de scores UCB para cada video candidato.
        """
        self.theta = self.A_inv.dot(self.b)
        recompensas_esperadas = contextos.dot(self.theta)
        incertidumbres = self.alpha * np.sqrt(np.sum(contextos.dot(self.A_inv) * contextos, axis=1))
        bonus_exploracion = self._calcular_exploracion_adaptativa(contextos)
        ucb = recompensas_esperadas + incertidumbres + bonus_exploracion
        return ucb

    def _calcular_exploracion_adaptativa(self, contextos):
        """
        Calcula bonus de exploracion adaptativo basado en varianza de recompensas.
        Mayor varianza = mayor exploracion. Retorna menor exploracion en primeras 10 selecciones.
        """
        if len(self.historial_recompensas) < 10:
            return np.full(len(contextos), 0.7)

        recompensas_recientes = self.historial_recompensas[-50:]
        varianza_recompensas = np.var(recompensas_recientes)
        factor_exploracion = self.beta * varianza_recompensas * 1.3
        return factor_exploracion * np.random.uniform(0, 1, len(contextos))

    def actualizar(self, contexto, recompensa):
        """
        Actualiza modelo con feedback de usuario (contexto y recompensa).
        Recalcula matrices A, b y theta usando Ridge Regression online.
        Mantiene historial de ultimas 1000 interacciones.
        """
        self.A += np.outer(contexto, contexto)
        self.b += recompensa * contexto
        self.A_inv = np.linalg.inv(self.A + 0.001 * np.identity(self.n_features))
        self.historial_recompensas.append(recompensa)
        self.historial_contextos.append(contexto)

        if len(self.historial_recompensas) > 1000:
            self.historial_recompensas = self.historial_recompensas[-500:]
            self.historial_contextos = self.historial_contextos[-500:]

    def obtener_estadisticas_rendimiento(self):
        """
        Obtiene metricas de rendimiento del bandit.
        Retorna recompensa promedio total, reciente y numero de selecciones.
        """
        if len(self.historial_recompensas) == 0:
            return {'recompensa_promedio': 0, 'total_selecciones': 0}

        return {
            'recompensa_promedio': np.mean(self.historial_recompensas),
            'total_selecciones': len(self.historial_recompensas),
            'promedio_reciente': np.mean(self.historial_recompensas[-50:]) if len(self.historial_recompensas) >= 50 else np.mean(self.historial_recompensas)
        }


class RecommendationEngine:
    """
    Motor de recomendaciones singleton con bandits contextuales.
    Implementa patron mixto VMP-AU-AU-VMP-NU-FW para feed infinito.
    Combina collaborative filtering, content-based y social signals.
    Usa embeddings de skills, grafo social y scores precalculados.
    """

    _instancia = None
    _inicializado = False

    def __new__(cls, data_service=None):
        cls._instancia = super(RecommendationEngine, cls).__new__(cls)
        return cls._instancia

    def __init__(self, data_service):
        """
        Inicializa motor de recomendaciones con datos desde DataService.
        Construye embeddings, grafo social, matrices lookup y bandits.
        Precalcula scores avanzados para optimizar seleccion de videos.
        """
        self.data_service = data_service
        self.videos_df = data_service.videos_df
        self.interactions_df = data_service.interactions_df
        self.flows_df = data_service.flows_df
        self.connections_df = data_service.connections_df
        self.patron = ['VMP', 'AU', 'AU', 'VMP', 'NU', 'FW']
        self.longitud_patron = len(self.patron)
        self.videos_por_respuesta = 24

        logger.info(f"Inicializando recommender con {len(self.flows_df)} flows")

        self._cachear_datos_videos()
        self._construir_embeddings_skills()
        self._construir_grafo_social()
        self._construir_matrices_lookup()
        self._inicializar_bandits()
        self._precalcular_scores_avanzados()

    def _cachear_datos_videos(self):
        """
        Construye cache de skills, knowledges, tools y languages por video.
        Extrae y parsea JSON de cada video a sets para lookup O(1).
        Mapea video_id a creator_id y video_url.
        """
        logger.info("Cacheando datos de videos para acceso rapido")

        self.cache_skills_video = {}
        self.cache_knowledges_video = {}
        self.cache_tools_video = {}
        self.cache_languages_video = {}
        self.video_a_creador = {}
        self.video_a_url = {}

        for idx, row in self.videos_df.iterrows():
            video_id = row['id']

            skills = set()
            try:
                if pd.notna(row.get('video_skills')):
                    skills_data = json.loads(row['video_skills']) if isinstance(row['video_skills'], str) else row['video_skills']
                    if isinstance(skills_data, list):
                        skills = set(skills_data[:5])
            except:
                pass

            knowledges = set()
            try:
                if pd.notna(row.get('video_knowledges')):
                    know_data = json.loads(row['video_knowledges']) if isinstance(row['video_knowledges'], str) else row['video_knowledges']
                    if isinstance(know_data, list):
                        knowledges = set(know_data[:3])
            except:
                pass

            tools = set()
            try:
                if pd.notna(row.get('video_tools')):
                    tools_data = json.loads(row['video_tools']) if isinstance(row['video_tools'], str) else row['video_tools']
                    if isinstance(tools_data, list):
                        tools = set(tools_data[:3])
            except:
                pass

            languages = set()
            try:
                if pd.notna(row.get('video_languages')):
                    lang_data = json.loads(row['video_languages']) if isinstance(row['video_languages'], str) else row['video_languages']
                    if isinstance(lang_data, list):
                        languages = set(lang_data[:3])
            except:
                pass

            self.cache_skills_video[video_id] = skills
            self.cache_knowledges_video[video_id] = knowledges
            self.cache_tools_video[video_id] = tools
            self.cache_languages_video[video_id] = languages
            self.video_a_creador[video_id] = row['user_id']
            self.video_a_url[video_id] = row['video']

        logger.info(f"Datos cacheados para {len(self.cache_skills_video)} videos")

    def _video_en_lista_negra(self, video_id):
        """
        Verifica si un video esta en la blacklist de URLs.
        Retorna True si la URL del video esta bloqueada.
        """
        if video_id not in self.video_a_url:
            return False
        video_url = self.video_a_url[video_id]
        return video_url in self.data_service.lista_negra

    def _construir_embeddings_skills(self):
        """
        Construye embeddings de skills usando matriz de coocurrencia normalizada.
        Calcula frecuencias de skills y relaciones entre ellos.
        Genera skill_a_idx, idx_a_skill y embeddings_skills para similitud.
        """
        logger.info("Construyendo embeddings avanzados de skills")

        todos_skills = set()
        for skills in self.cache_skills_video.values():
            todos_skills.update(skills)

        self.skill_a_idx = {skill: idx for idx, skill in enumerate(sorted(todos_skills))}
        self.idx_a_skill = {idx: skill for skill, idx in self.skill_a_idx.items()}
        n_skills = len(self.skill_a_idx)

        coocurrencia = np.zeros((n_skills, n_skills))
        conteo_skills = Counter()

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

    def _construir_grafo_social(self):
        """
        Construye grafo de conexiones sociales entre usuarios.
        Calcula scores de influencia basados en numero de conexiones (log scale).
        Genera grafo_social y influencia_social para social signals.
        """
        logger.info("Construyendo grafo social con scores de influencia")

        self.grafo_social = defaultdict(set)
        self.influencia_social = defaultdict(float)

        if self.connections_df is not None and len(self.connections_df) > 0:
            for _, row in self.connections_df.iterrows():
                self.grafo_social[row['user_id']].add(row['connected_user_id'])

            for user_id, conexiones in self.grafo_social.items():
                self.influencia_social[user_id] = np.log1p(len(conexiones)) / 10.0

        logger.info(f"Grafo social construido: {len(self.grafo_social)} usuarios")

    def _construir_matrices_lookup(self):
        """
        Pre-construye matrices y diccionarios de lookup para procesamiento vectorizado.
        Crea indices rapidos para skills, knowledges, tools y languages.
        Genera matrices binarias por video para calculo batch de similitudes.
        """
        logger.info("Pre-construyendo matrices de lookup para vectorizacion")

        todos_skills = sorted(set().union(*self.cache_skills_video.values()))
        todos_knowledges = sorted(set().union(*self.cache_knowledges_video.values()))
        todos_tools = sorted(set().union(*self.cache_tools_video.values()))
        todos_languages = sorted(set().union(*self.cache_languages_video.values()))

        self.all_skills = todos_skills
        self.all_knowledges = todos_knowledges
        self.all_tools = todos_tools
        self.all_languages = todos_languages

        self.skill_to_idx_fast = {s: i for i, s in enumerate(todos_skills)}
        self.knowledge_to_idx_fast = {k: i for i, k in enumerate(todos_knowledges)}
        self.tool_to_idx_fast = {t: i for i, t in enumerate(todos_tools)}
        self.language_to_idx_fast = {l: i for i, l in enumerate(todos_languages)}

        logger.info("Matrices de lookup construidas")

    def _inicializar_bandits(self):
        """
        Inicializa bandits contextuales para cada categoria de video.
        VMP (alpha=1.5), AU (alpha=1.8), NU (alpha=2.5) con mayor exploracion para nuevos.
        Cada bandit aprende independientemente de feedback de usuarios.
        """
        logger.info("Inicializando bandits contextuales adaptativos")

        n_features = 18
        self.bandit_vmp = BanditContextualAdaptativo(n_features, alpha=1.5, beta=0.8)
        self.bandit_au = BanditContextualAdaptativo(n_features, alpha=1.8, beta=1.0)
        self.bandit_nu = BanditContextualAdaptativo(n_features, alpha=2.5, beta=1.3)

    def _precalcular_scores_avanzados(self):
        """
        Precalcula multiples scores combinados para cada video.
        Calcula engagement, temporal, calidad, popularidad, diversidad y rareza.
        Normaliza metricas y aplica transformaciones logaritmicas.
        Genera columnas agregadas en videos_df para lookup rapido.
        """
        logger.info("Precalculando scores avanzados con gates de calidad")

        df = self.videos_df.copy()

        views_log = np.log1p(df['views'].astype(float))
        views_norm = (views_log - views_log.min()) / (views_log.max() - views_log.min() + 1e-6)

        rating_norm = df['avg_rating'].astype(float) / 5.0

        connections_log = np.log1p(df['connection_count'].astype(float))
        connections_norm = (connections_log - connections_log.min()) / (connections_log.max() - connections_log.min() + 1e-6)

        df['score_engagement'] = (
            views_norm * 0.35 +
            rating_norm * 0.40 +
            connections_norm * 0.25
        )

        df['score_temporal'] = np.exp(-df['days_since_creation'].astype(float) / 28.0)

        contenido_ultra_nuevo = df['days_since_creation'] <= 30
        df['boost_nuevo'] = 1.0
        df.loc[contenido_ultra_nuevo, 'boost_nuevo'] = 1.5

        peso_rating = df['rating_count'].astype(float) / (df['rating_count'].astype(float) + 10)
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
                rarezas = [1.0 / (self.conteo_skills.get(s, 1) + 1) for s in skills]
                scores_rareza_skills.append(np.mean(rarezas) * 100)
            else:
                scores_rareza_skills.append(0)

        df['diversidad_skills'] = scores_diversidad_skills
        df['rareza_skills'] = scores_rareza_skills

        gate_calidad = (
            (df['avg_rating'] >= 3.0) |
            (df['views'] >= 20) |
            (df['connection_count'] >= 2) |
            (df['rating_count'] >= 2)
        )
        df['pasa_gate_calidad'] = gate_calidad.astype(int)

        self.videos_df = df

        logger.info("Scores avanzados precalculados con filtros de calidad estrictos")

    def _obtener_preferencias_usuario_rapido(self, user_id):
        """
        Extrae preferencias de usuario desde interacciones pasadas.
        Calcula skills, knowledges, tools, languages, ciudades, red social y vector de skills.
        Retorna diccionario con preferencias agregadas y ponderadas.
        """
        prefs = {
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

        if len(self.interactions_df) == 0 or 'user_id' not in self.interactions_df.columns:
            return prefs

        interacciones_usuario = self.interactions_df[self.interactions_df['user_id'] == user_id]

        if len(interacciones_usuario) == 0:
            return prefs

        prefs['vistos'] = set(interacciones_usuario['video_id'].tolist())
        prefs['red_social'] = self.grafo_social.get(user_id, set())
        prefs['score_influencia_social'] = self.influencia_social.get(user_id, 0)

        muestra_vistos = list(prefs['vistos'])[:80]

        contador_skills = Counter()
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
            prefs['pesos_skills'] = {s: c/total_conteo for s, c in contador_skills.items()}

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

    def _calcular_similitudes_skills_lote(self, ids_videos, prefs_usuario):
        """
        Calcula similitud coseno entre skills de usuario y videos en batch.
        Combina similitud vectorial (60%) con solapamiento ponderado (40%).
        Retorna array de similitudes normalizadas entre 0 y 1.
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
                    solapamiento_ponderado = sum(prefs_usuario['pesos_skills'].get(s, 0) for s in skills_vid)

                    sim_combinada = sim * 0.6 + solapamiento_ponderado * 0.4
                    similitudes.append(max(0, min(1, sim_combinada)))
                else:
                    similitudes.append(0.3)
            else:
                similitudes.append(0.3)

        return np.array(similitudes)

    def _calcular_match_extendido_vectorizado(self, ids_videos, prefs_usuario):
        """
        Calcula match score entre preferencias de usuario y atributos de videos.
        Combina skills (55%), knowledges (20%), tools (15%) y languages (10%).
        Retorna array de scores de match normalizados.
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

    def _extraer_features_contexto_vectorizado(self, df_candidatos, prefs_usuario):
        """
        Extrae 18 features contextuales para cada video candidato.
        Combina engagement, temporal, calidad, social, diversidad y rareza.
        Retorna matriz numpy (n_videos, 18) normalizada para bandits.
        """
        n_candidatos = len(df_candidatos)
        features = np.zeros((n_candidatos, 18))

        features[:, 0] = df_candidatos['score_engagement'].values
        features[:, 1] = df_candidatos['score_temporal'].values * df_candidatos['boost_nuevo'].values
        features[:, 2] = df_candidatos['score_calidad'].values
        features[:, 3] = df_candidatos['score_popularidad'].values
        features[:, 4] = df_candidatos['diversidad_skills'].values

        ids_videos = df_candidatos['id'].tolist()
        features[:, 5] = self._calcular_similitudes_skills_lote(ids_videos, prefs_usuario)

        features[:, 6] = self._calcular_match_extendido_vectorizado(ids_videos, prefs_usuario) / 100.0

        coincidencias_ciudad = df_candidatos['city'].isin(prefs_usuario['cities']).astype(float).values
        features[:, 7] = coincidencias_ciudad

        coincidencias_sociales = df_candidatos['user_id'].isin(prefs_usuario['red_social']).astype(float).values
        features[:, 8] = coincidencias_sociales

        features[:, 9] = np.log1p(df_candidatos['views'].values) / 10.0
        features[:, 10] = df_candidatos['avg_rating'].values / 5.0

        features[:, 11] = df_candidatos['rareza_skills'].values / 100.0

        features[:, 12] = df_candidatos['pasa_gate_calidad'].values

        features[:, 13] = prefs_usuario['score_influencia_social']

        features[:, 14] = df_candidatos['rating_count'].values / (df_candidatos['rating_count'].values.max() + 1)

        features[:, 15] = df_candidatos['like_count'].values / (df_candidatos['like_count'].values.max() + 1)

        features[:, 16] = df_candidatos['exhibited_count'].values / (df_candidatos['exhibited_count'].values.max() + 1)

        features[:, 17] = np.random.uniform(0, 0.3, n_candidatos)

        return features

    def _seleccionar_vmp_rapido(self, ids_excluir, prefs_usuario, creadores_usados, n=110):
        """
        Selecciona videos VMP (Muy Mejor Puntuados) usando bandit contextual.
        Filtra por calidad, aplica UCB y combina con engagement/popularidad.
        Prioriza contenido nuevo (<45 dias). Retorna lista de video IDs.
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

        features = self._extraer_features_contexto_vectorizado(candidatos, prefs_usuario)

        scores_ucb = self.bandit_vmp.seleccionar_lote(features)

        candidatos['score_vmp'] = scores_ucb
        candidatos['score_vmp'] += candidatos['score_engagement'] * 2.2
        candidatos['score_vmp'] += candidatos['score_popularidad'] * 1.6
        candidatos['score_vmp'] += candidatos['score_calidad'] * 1.8

        mascara_nuevo_contenido = candidatos['days_since_creation'] <= 45
        candidatos.loc[mascara_nuevo_contenido, 'score_vmp'] += 1.4

        top_candidatos = candidatos.nlargest(min(n*2, len(candidatos)), 'score_vmp')

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

    def _seleccionar_nu_rapido(self, ids_excluir, prefs_usuario, creadores_usados, n=95):
        """
        Selecciona videos NU (Nuevo) usando bandit contextual.
        Filtra solo contenido reciente (<45 dias) y prioriza diversidad/rareza.
        Aplica muestreo aleatorio ponderado. Retorna lista de video IDs.
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados)) &
            (self.videos_df['days_since_creation'] <= 45)
        ].copy()

        if len(candidatos) == 0:
            return []

        features = self._extraer_features_contexto_vectorizado(candidatos, prefs_usuario)

        scores_ucb = self.bandit_nu.seleccionar_lote(features)

        candidatos['score_nu'] = scores_ucb
        candidatos['score_nu'] += candidatos['score_temporal'] * 2.5
        candidatos['score_nu'] += candidatos['diversidad_skills'] * 1.8
        candidatos['score_nu'] += candidatos['rareza_skills'] / 100.0 * 1.4
        candidatos['score_nu'] += candidatos['boost_nuevo'] * 0.8
        candidatos['score_nu'] += np.random.uniform(0, 0.6, len(candidatos))

        top_candidatos = candidatos.nlargest(min(n*2, len(candidatos)), 'score_nu')

        if len(top_candidatos) > n:
            return top_candidatos.sample(n=n)['id'].tolist()

        return top_candidatos['id'].tolist()

    def _seleccionar_au_rapido(self, ids_excluir, prefs_usuario, creadores_usados, n=170):
        """
        Selecciona videos AU (Afin al Usuario) usando bandit contextual.
        Prioriza similitud de skills, match extendido y señales sociales.
        Aplica muestreo ponderado por scores. Retorna lista de video IDs.
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados))
        ].copy()

        if len(candidatos) == 0:
            return []

        features = self._extraer_features_contexto_vectorizado(candidatos, prefs_usuario)

        scores_ucb = self.bandit_au.seleccionar_lote(features)

        candidatos['score_au'] = scores_ucb
        candidatos['score_au'] += features[:, 5] * 2.8
        candidatos['score_au'] += features[:, 6] * 2.5
        candidatos['score_au'] += candidatos['score_popularidad'] * 1.1
        candidatos['score_au'] += candidatos['score_calidad'] * 1.4
        candidatos['score_au'] += candidatos['score_temporal'] * 0.9
        candidatos['score_au'] += candidatos['rareza_skills'] / 100.0 * 0.9

        mascara_nuevo_contenido = candidatos['days_since_creation'] <= 45
        candidatos.loc[mascara_nuevo_contenido, 'score_au'] += 0.9

        top_candidatos = candidatos.nlargest(min(n, len(candidatos)), 'score_au')

        return top_candidatos['id'].tolist()

    def _seleccionar_flows(self, ids_excluir, creadores_usados, n=40):
        """
        Selecciona challenges/flows para categoria FW (Flows).
        Prioriza contenido reciente con score aleatorio + temporal.
        Retorna lista de flow IDs.
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

    def _seleccionar_boost_exploracion(self, ids_excluir, creadores_usados, n=75):
        """
        Selecciona videos aleatorios para boost de exploracion.
        Muestreo completamente aleatorio sin scoring.
        Retorna lista de video IDs.
        """
        candidatos = self.videos_df[
            (~self.videos_df['id'].isin(ids_excluir)) &
            (~self.videos_df['user_id'].isin(creadores_usados))
        ]

        if len(candidatos) == 0:
            return []

        tamanio_muestra = min(n, len(candidatos))
        return candidatos.sample(n=tamanio_muestra)['id'].tolist()

    def generar_scroll_infinito(self, user_id, n_videos=24, videos_excluidos=None, incluir_fw=True):
        """
        Genera feed infinito mezclando videos y flows segun patron VMP-AU-AU-VMP-NU-FW.
        Siempre devuelve 24 videos (4 repeticiones del patron de 6).
        No repite creadores en 12 videos consecutivos (2 patrones).
        Retorna diccionario con videos, flows, tipo_patron y metricas de rendimiento.
        """
        n_videos = self.videos_por_respuesta
        tiempo_inicio = time.time()

        logger.info(f"Generando scroll infinito para usuario {user_id}")

        prefs_usuario = self._obtener_preferencias_usuario_rapido(user_id)

        ids_excluir = prefs_usuario['vistos'].copy()
        if videos_excluidos:
            ids_excluir.update(videos_excluidos)
            logger.info(f"Videos excluidos por historial: {len(videos_excluidos)}")

        creadores_usados = set()

        pool_vmp = self._seleccionar_vmp_rapido(ids_excluir, prefs_usuario, creadores_usados, n=110)
        pool_nu = self._seleccionar_nu_rapido(ids_excluir, prefs_usuario, creadores_usados, n=95)
        excluir_para_au = ids_excluir | set(pool_vmp) | set(pool_nu)
        pool_au = self._seleccionar_au_rapido(excluir_para_au, prefs_usuario, creadores_usados, n=170)
        if incluir_fw:
            pool_flows = self._seleccionar_flows(ids_excluir, creadores_usados, n=40)
        else:
            pool_flows = []
        pool_exploracion = self._seleccionar_boost_exploracion(excluir_para_au | set(pool_au), creadores_usados, n=75)

        logger.info(f"Pools generados - VMP: {len(pool_vmp)}, NU: {len(pool_nu)}, AU: {len(pool_au)}, FLOWS: {len(pool_flows)}, EXPLORE: {len(pool_exploracion)}")

        feed = []
        ids_usados = set()
        skills_usados = set()
        creadores_usados_en_feed = set()
        creadores_por_ventana = []

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

                if len(feed) > 0 and len(feed) % 12 == 0:
                    if len(creadores_por_ventana) >= 12:
                        creadores_a_remover = creadores_por_ventana[:12]
                        creadores_usados_en_feed = set([c for c in creadores_usados_en_feed if c not in creadores_a_remover])
                        creadores_por_ventana = creadores_por_ventana[12:]

                tipo_slot = self.patron[pos_patron]
                video_id = None
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
                            if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
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
                                if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
                                    video_id = vid
                                    skills_usados.update(self.cache_skills_video.get(vid, set()))
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
                            if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
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
                                if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
                                    video_id = vid
                                    skills_usados.update(self.cache_skills_video.get(vid, set()))
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
                            if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
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
                                if creador_vid is not None and creador_vid not in creadores_usados_en_feed:
                                    video_id = vid
                                    skills_usados.update(self.cache_skills_video.get(vid, set()))
                                    creadores_usados_en_feed.add(creador_vid)
                                    creadores_por_ventana.append(creador_vid)
                                    break

                if video_id:
                    if es_flow:
                        datos_flow = self.flows_df[self.flows_df['id'] == video_id].iloc[0]
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
                        datos_video = self.videos_df[self.videos_df['id'] == video_id].iloc[0]
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
            catalogo_disponible = catalogo_disponible - len(videos_excluidos - prefs_usuario['vistos'])

        todos_pools = set(pool_vmp) | set(pool_nu) | set(pool_au) | set(pool_flows) | set(pool_exploracion)
        cobertura_catalogo = len(todos_pools) / max(catalogo_disponible, 1) * 100

        cobertura_feed = len(ids_usados) / max(n_videos, 1) * 100

        conteo_contenido_nuevo = sum(1 for item in feed if item['days_old'] <= 45)
        ratio_contenido_nuevo = conteo_contenido_nuevo / len(feed) * 100 if len(feed) > 0 else 0

        skills_diversos = set()
        creadores_diversos = set()
        for item in feed:
            video_id = item['video_id']
            if video_id in self.cache_skills_video:
                skills_diversos.update(self.cache_skills_video[video_id])
            if item['type'] != 'FW':
                datos_video = self.videos_df[self.videos_df['id'] == video_id]
                if len(datos_video) > 0:
                    creadores_diversos.add(datos_video.iloc[0]['user_id'])

        diversidad_skills = len(skills_diversos) / max(len(feed) * 2, 1) * 100
        diversidad_creadores = len(creadores_usados_en_feed) / max(len(feed), 1) * 100

        metricas = {
            'total_videos': len(feed),
            'type_distribution': dict(conteos_tipo),
            'unique_creators': len(creadores_usados_en_feed),
            'avg_views': float(np.mean([item['views'] for item in feed if item['type'] != 'FW'])) if any(item['type'] != 'FW' for item in feed) else 0,
            'avg_rating': float(np.mean([item['rating'] for item in feed if item['type'] != 'FW'])) if any(item['type'] != 'FW' for item in feed) else 0,
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

    def _obtener_flows_vistos_usuario(self, user_id):
        """
        Consulta activity_log para obtener flows ya vistos por el usuario.
        Retorna set de flow IDs que el usuario ya vio.
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
            flows_vistos = set([int(row['subject_id']) for row in result if row['subject_id']])

            conn.close()
            logger.info(f"Usuario {user_id} ha visto {len(flows_vistos)} flows")
            return flows_vistos

        except Exception as e:
            logger.error(f"Error obteniendo flows vistos usuario {user_id}: {e}")
            return set()

    def _seleccionar_flows_para_usuario(self, user_id, n=24, excluded_ids=[]):
        """
        Selecciona flows ordenados por relevancia para el usuario.
        No repite flows hasta agotar todos los disponibles.
        Excluye flows en excluded_ids para scroll infinito.
        """
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

    def generar_feed_flows_only(self, user_id, n_flows=24, excluded_ids=[]):
        """
        Genera feed de SOLO flows para endpoint be_discover.
        Siempre devuelve 24 flows ordenados por relevancia.
        Excluye flows en excluded_ids para scroll infinito.
        """
        tiempo_inicio = time.time()

        logger.info(f"Generando feed flows_only para usuario {user_id}, excluyendo {len(excluded_ids)} flows")

        flow_ids = self._seleccionar_flows_para_usuario(user_id, n=n_flows, excluded_ids=excluded_ids)

        feed = []
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

        logger.info(f"Feed flows_only generado: {len(feed)} flows en {tiempo_exec:.3f}s")

        return feed, metricas
