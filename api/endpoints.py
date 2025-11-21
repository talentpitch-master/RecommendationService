import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Union

import pandas as pd
from fastapi import APIRouter, Request, BackgroundTasks, Depends

from core.config import Config
from core.database import MySQLConnection
from services.data_service import DataService
from services.recommendation import RecommendationEngine
from services.tracking import ActivityTracker
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

router = APIRouter()

_data_service_instance: Optional[DataService] = None
_recommendation_engine_instance: Optional[RecommendationEngine] = None


def get_config() -> Config:
    """
    Obtiene instancia de configuracion.

    Returns:
        Instancia de Config
    """
    return Config()


def get_data_service() -> DataService:
    """
    Obtiene instancia singleton de DataService.

    Carga datos de MySQL en memoria en primera invocacion.

    Returns:
        Instancia de DataService con datos cargados
    """
    global _data_service_instance
    if _data_service_instance is None:
        _data_service_instance = DataService(MySQLConnection)
        _data_service_instance.load_all_data()
    return _data_service_instance


def get_recommendation_engine() -> RecommendationEngine:
    """
    Obtiene instancia singleton de RecommendationEngine.

    Inicializa motor de bandits contextuales y embeddings en primera invocacion.

    Returns:
        Instancia de RecommendationEngine
    """
    global _recommendation_engine_instance
    if _recommendation_engine_instance is None:
        data_service = get_data_service()
        _recommendation_engine_instance = RecommendationEngine(data_service)
    return _recommendation_engine_instance


def get_activity_tracker() -> ActivityTracker:
    """
    Obtiene instancia de ActivityTracker.

    Returns:
        Instancia de ActivityTracker
    """
    return ActivityTracker()


async def async_flush_activity(
    user_id: int,
    tracker: ActivityTracker
) -> None:
    """
    Ejecuta flush asincrono de actividades de usuario.

    Args:
        user_id: ID del usuario
        tracker: Instancia de ActivityTracker
    """
    try:
        count = tracker.flush_user_activity_to_mysql(user_id)
        logger.info(f"Flush async user {user_id}: {count} actividades")
    except Exception as e:
        logger.error(f"Error flush async user {user_id}: {e}")


def parse_excluded_ids(excluded_ids: Union[str, List[int], None]) -> List[int]:
    """
    Parsea IDs excluidos desde diferentes formatos.

    Args:
        excluded_ids: IDs como string separado por comas o lista de enteros

    Returns:
        Lista de IDs como enteros
    """
    if excluded_ids is None:
        return []

    if isinstance(excluded_ids, str) and excluded_ids:
        return [int(x) for x in excluded_ids.split(',') if x.strip().isdigit()]

    if isinstance(excluded_ids, list):
        return [int(x) for x in excluded_ids if isinstance(x, (int, str))]

    return []


def parse_json_field(
    data: pd.Series,
    field_name: str,
    default: Any = None
) -> Any:
    """
    Parsea campo JSON de forma segura.

    Args:
        data: Serie de pandas con los datos
        field_name: Nombre del campo a parsear
        default: Valor por defecto si falla el parsing

    Returns:
        Datos parseados o valor por defecto
    """
    try:
        field_value = data.get(field_name)
        if pd.notna(field_value):
            parsed = (
                json.loads(field_value)
                if isinstance(field_value, str)
                else field_value
            )
            if isinstance(parsed, list):
                return parsed
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"Error parsing {field_name}: {e}")

    return default if default is not None else []


def build_challenge_item(
    video_id: int,
    flow_data: pd.Series,
    position: int
) -> Dict[str, Any]:
    """
    Construye objeto de challenge para respuesta.

    Args:
        video_id: ID del challenge
        flow_data: Serie de pandas con datos del flow
        position: Posicion en el feed

    Returns:
        Diccionario con datos del challenge
    """
    interest_areas = parse_json_field(flow_data, 'interest_areas', [])
    type_objectives = parse_json_field(flow_data, 'type_objectives', ["hire"])

    created_at = flow_data['created_at']
    created_at_str = (
        created_at.isoformat()
        if hasattr(created_at, 'isoformat')
        else str(created_at)
    )

    challenge_obj = {
        "type": "challenge",
        "id": int(video_id),
        "name": flow_data.get('name', ''),
        "slug": flow_data.get('slug', ''),
        "description": flow_data.get('description', ''),
        "video_url": flow_data['video'],
        "image": flow_data.get('image', flow_data['video']),
        "user_id": int(flow_data['user_id']),
        "user_name": flow_data.get('creator_name', ''),
        "user_slug": flow_data.get('creator_slug', ''),
        "user_avatar": (
            f"https://media.talentpitch.co/users/"
            f"{flow_data['user_id']}/avatar-100.png"
        ),
        "talent_type": flow_data.get('talent_type', 'innovators'),
        "interest_areas": interest_areas,
        "type_objectives": type_objectives,
        "top": True,
        "created_at": created_at_str,
        "updated_at": datetime.now().isoformat()
    }

    if pd.notna(flow_data.get('status_at')):
        challenge_obj["status_at"] = str(flow_data['status_at'])

    return challenge_obj


def build_resume_item(
    video_id: int,
    video_data: pd.Series
) -> Dict[str, Any]:
    """
    Construye objeto de resume para respuesta.

    Args:
        video_id: ID del resume
        video_data: Serie de pandas con datos del video

    Returns:
        Diccionario con datos del resume
    """
    creator_name = video_data.get('creator_name', '')
    slug = f"{creator_name.lower().replace(' ', '-')}-{video_id}"

    return {
        "type": "resume",
        "id": int(video_id),
        "name": creator_name,
        "slug": slug,
        "description": video_data.get('description', ''),
        "video": video_data['video'],
        "image": video_data.get('image', video_data['video']),
        "user_id": int(video_data['user_id']),
        "user_name": creator_name,
        "user_slug": creator_name.lower().replace(' ', '-'),
        "avatar": (
            f"https://media.talentpitch.co/users/"
            f"{video_data['user_id']}/avatar-100.png"
        ),
        "main_objective": "be_discovered",
        "type_audience": "innovators",
        "type_audiences": ["innovators"],
        "interest_areas": [],
        "role_objectives": [],
        "connected": ""
    }


@router.post("/search/total")
async def total(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    recommendation_engine: RecommendationEngine = Depends(
        get_recommendation_engine
    ),
    tracker: ActivityTracker = Depends(get_activity_tracker),
    data_service: DataService = Depends(get_data_service)
) -> Dict[str, Any]:
    """
    Endpoint de feed mixto con videos y challenges.

    Args:
        request: Request de FastAPI
        background_tasks: Background tasks de FastAPI
        config: Configuracion de la aplicacion
        recommendation_engine: Motor de recomendaciones
        tracker: Tracker de actividades
        data_service: Servicio de datos

    Returns:
        Diccionario con statusCode y body con mix_ids e items
    """
    data = await request.json()
    user_id = data.get('SELF_ID', data.get('user_id', 0))
    session_id = data.get('session_id', None)

    excluded_ids_raw = data.get(
        'excluded_ids',
        data.get('LAST_IDS', data.get('videos_excluidos', []))
    )
    excluded_ids = parse_excluded_ids(excluded_ids_raw)

    tracker.track_feed_request(
        user_id,
        'total',
        {'excluded_count': len(excluded_ids)},
        session_id
    )

    feed, metricas = recommendation_engine.generar_scroll_infinito(
        user_id,
        n_videos=24,
        videos_excluidos=excluded_ids
    )

    all_items: List[Dict[str, Any]] = []
    challenge_ids: List[str] = []
    resume_ids: List[str] = []

    for item in feed:
        video_id = item['video_id']
        item_type = item['type']

        if item_type == 'challenge':
            flow_row = data_service.flows_df[
                data_service.flows_df['id'] == video_id
            ]
            if len(flow_row) > 0:
                challenge_obj = build_challenge_item(
                    video_id,
                    flow_row.iloc[0],
                    item['position']
                )
                all_items.append(challenge_obj)
                challenge_ids.append(str(video_id))
        else:
            video_row = data_service.videos_df[
                data_service.videos_df['id'] == video_id
            ]
            if len(video_row) > 0:
                resume_obj = build_resume_item(video_id, video_row.iloc[0])
                all_items.append(resume_obj)
                resume_ids.append(str(video_id))

        tracker.track_video_view(
            user_id,
            video_id,
            item['video_url'],
            item['position'],
            item['patron_type'],
            session_id
        )

    if len(all_items) >= config.FLUSH_THRESHOLD_ACTIVITIES:
        background_tasks.add_task(async_flush_activity, user_id, tracker)

    mix_ids = [str(item['id']) for item in all_items]

    return {
        "statusCode": 200,
        "body": {
            "mix_ids": mix_ids,
            "items": all_items
        }
    }


@router.post("/search/discover")
async def discover(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    recommendation_engine: RecommendationEngine = Depends(
        get_recommendation_engine
    ),
    tracker: ActivityTracker = Depends(get_activity_tracker),
    data_service: DataService = Depends(get_data_service)
) -> Dict[str, Any]:
    """
    Endpoint de feed de solo resumes.

    Args:
        request: Request de FastAPI
        background_tasks: Background tasks de FastAPI
        config: Configuracion de la aplicacion
        recommendation_engine: Motor de recomendaciones
        tracker: Tracker de actividades
        data_service: Servicio de datos

    Returns:
        Diccionario con statusCode y body con resume_ids e items
    """
    data = await request.json()
    user_id = data.get('SELF_ID', data.get('user_id', 0))
    max_size = min(data.get('MAX_SIZE', data.get('size', 20)), 100)
    session_id = data.get('session_id', None)

    last_ids_raw = data.get('LAST_IDS', data.get('videos_excluidos', []))
    last_ids = parse_excluded_ids(last_ids_raw)

    tracker.track_feed_request(user_id, 'discover', {'size': max_size}, session_id)

    feed, metricas = recommendation_engine.generar_scroll_infinito(
        user_id,
        n_videos=24,
        videos_excluidos=last_ids,
        incluir_fw=False
    )

    resumes_items: List[Dict[str, Any]] = []
    resume_ids: List[str] = []

    for item in feed:
        if item['type'] != 'FW':
            video_id = item['video_id']
            video_row = data_service.videos_df[
                data_service.videos_df['id'] == video_id
            ]

            if len(video_row) > 0:
                resume_obj = build_resume_item(video_id, video_row.iloc[0])
                resumes_items.append(resume_obj)
                resume_ids.append(str(video_id))

                tracker.track_video_view(
                    user_id,
                    video_id,
                    item['video_url'],
                    item['position'],
                    item['type'],
                    session_id
                )

    if len(resumes_items) >= config.FLUSH_THRESHOLD_ACTIVITIES:
        background_tasks.add_task(async_flush_activity, user_id, tracker)

    return {
        "statusCode": 200,
        "body": {
            "resume_ids": resume_ids,
            "items": resumes_items
        }
    }


@router.post("/search/flow")
async def flow(
    request: Request,
    background_tasks: BackgroundTasks,
    config: Config = Depends(get_config),
    recommendation_engine: RecommendationEngine = Depends(
        get_recommendation_engine
    ),
    tracker: ActivityTracker = Depends(get_activity_tracker),
    data_service: DataService = Depends(get_data_service)
) -> Dict[str, Any]:
    """
    Endpoint de feed de solo flows.

    Args:
        request: Request de FastAPI
        background_tasks: Background tasks de FastAPI
        config: Configuracion de la aplicacion
        recommendation_engine: Motor de recomendaciones
        tracker: Tracker de actividades
        data_service: Servicio de datos

    Returns:
        Diccionario con statusCode y body con challenge_ids e items
    """
    data = await request.json()
    user_id = data.get('user_id', data.get('SELF_ID', 0))
    max_size = min(data.get('size', data.get('MAX_SIZE', 18)), 100)
    session_id = data.get('session_id', None)

    last_ids_raw = data.get('videos_excluidos', data.get('LAST_IDS', []))
    last_ids = parse_excluded_ids(last_ids_raw)

    tracker.track_feed_request(user_id, 'flow', {'size': max_size}, session_id)

    feed_result, metricas = recommendation_engine.generar_feed_flows_only(
        user_id,
        n_flows=24,
        excluded_ids=last_ids
    )

    all_items: List[Dict[str, Any]] = []
    challenge_ids: List[str] = []

    for item in feed_result:
        video_id = item['video_id']
        flow_data = item['flow_data']

        challenge_obj = build_challenge_item(
            video_id,
            flow_data,
            item['position']
        )

        all_items.append(challenge_obj)
        challenge_ids.append(str(video_id))

        tracker.track_video_view(
            user_id,
            video_id,
            flow_data['video'],
            item['position'],
            'FW',
            session_id
        )

    if len(all_items) >= config.FLUSH_THRESHOLD_ACTIVITIES:
        background_tasks.add_task(async_flush_activity, user_id, tracker)

    return {
        "statusCode": 200,
        "body": {
            "challenge_ids": challenge_ids,
            "items": all_items
        }
    }


@router.post("/search/reload")
async def reload_data() -> Dict[str, Any]:
    """
    Recarga datos desde MySQL y reinicializa motor de recomendaciones.

    Returns:
        Diccionario con statusCode y mensaje
    """
    global _data_service_instance, _recommendation_engine_instance

    _data_service_instance = None
    _recommendation_engine_instance = None

    get_data_service()
    get_recommendation_engine()

    return {"statusCode": 200, "message": "Data reloaded successfully"}
