import json
import pandas as pd
from fastapi import APIRouter, Request, BackgroundTasks
from datetime import datetime
from core.database import MySQLConnection
from services.data_service import DataService
from services.tracking import ActivityTracker
from services.recommendation import RecommendationEngine
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

router = APIRouter()

_data_service_instance = None
_recommendation_engine_instance = None

def get_data_service():
    """
    Obtiene la instancia singleton de DataService.
    Carga todos los datos de MySQL en memoria si es la primera vez.
    """
    global _data_service_instance
    if _data_service_instance is None:
        _data_service_instance = DataService(MySQLConnection)
        _data_service_instance.load_all_data()
    return _data_service_instance

def get_recommendation_engine():
    """
    Obtiene la instancia singleton de RecommendationEngine.
    Inicializa el motor de bandits contextuales y embeddings si es la primera vez.
    """
    global _recommendation_engine_instance
    if _recommendation_engine_instance is None:
        data_service = get_data_service()
        _recommendation_engine_instance = RecommendationEngine(data_service)
    return _recommendation_engine_instance

def async_flush_activity(user_id: int):
    """
    Ejecuta flush asincrono de actividades de un usuario especifico.
    Transfiere actividades de Redis a tabla activity_log en MySQL.
    """
    try:
        tracker = ActivityTracker()
        count = tracker.flush_user_activity_to_mysql(user_id)
        logger.info(f"Flush async para user {user_id}: {count} actividades")
    except Exception as e:
        logger.error(f"Error flush async user {user_id}: {e}")

@router.post("/api/search/total")
async def total(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint para descubrir challenges/flows.
    Devuelve 24 flows ordenados por relevancia para el usuario.
    No repite flows hasta agotar todos los disponibles.
    """
    data = await request.json()
    user_id = data.get('SELF_ID', data.get('user_id', 0))
    session_id = data.get('session_id', None)

    excluded_ids = data.get('excluded_ids', data.get('LAST_IDS', data.get('videos_excluidos', [])))

    if isinstance(excluded_ids, str) and excluded_ids:
        excluded_ids = [int(x) for x in excluded_ids.split(',') if x]

    recommendation_engine = get_recommendation_engine()
    tracker = ActivityTracker()
    data_service = get_data_service()

    tracker.track_feed_request(user_id, 'total', {'excluded_count': len(excluded_ids)}, session_id)

    last_ids = excluded_ids
    feed, metricas = recommendation_engine.generar_scroll_infinito(user_id, n_videos=24, videos_excluidos=last_ids)

    all_items = []
    challenge_ids = []
    resume_ids = []

    for item in feed:
        video_id = item['video_id']
        item_type = item['type']

        if item_type == 'challenge':
            flow_row = data_service.flows_df[data_service.flows_df['id'] == video_id]
            if len(flow_row) > 0:
                flow_data = flow_row.iloc[0]

                interest_areas = []
                try:
                    if pd.notna(flow_data.get('interest_areas')):
                        areas_data = json.loads(flow_data['interest_areas']) if isinstance(flow_data['interest_areas'], str) else flow_data['interest_areas']
                        if isinstance(areas_data, list):
                            interest_areas = areas_data
                except:
                    pass

                type_objectives = []
                try:
                    if pd.notna(flow_data.get('type_objectives')):
                        obj_data = json.loads(flow_data['type_objectives']) if isinstance(flow_data['type_objectives'], str) else flow_data['type_objectives']
                        if isinstance(obj_data, list):
                            type_objectives = obj_data
                except:
                    type_objectives = ["hire"]

                challenge_obj = {
                    "type": "challenge",
                    "id": int(video_id),
                    "name": flow_data.get('name', ''),
                    "slug": flow_data.get('slug', ''),
                    "description": flow_data.get('description', ''),
                    "video_url": item['video_url'],
                    "image": flow_data.get('image', item['video_url']),
                    "user_id": int(flow_data['user_id']),
                    "user_name": flow_data.get('creator_name', ''),
                    "user_slug": flow_data.get('creator_slug', ''),
                    "user_avatar": f"https://media.talentpitch.co/users/{flow_data['user_id']}/avatar-100.png",
                    "talent_type": flow_data.get('talent_type', 'innovators'),
                    "interest_areas": interest_areas,
                    "type_objectives": type_objectives,
                    "top": True,
                    "created_at": flow_data['created_at'].isoformat() if hasattr(flow_data['created_at'], 'isoformat') else str(flow_data['created_at']),
                    "updated_at": datetime.now().isoformat()
                }

                if pd.notna(flow_data.get('status_at')):
                    challenge_obj["status_at"] = str(flow_data['status_at'])

                all_items.append(challenge_obj)
                challenge_ids.append(str(video_id))

        else:
            video_row = data_service.videos_df[data_service.videos_df['id'] == video_id]
            if len(video_row) > 0:
                video_data = video_row.iloc[0]

                resume_obj = {
                    "type": "resume",
                    "id": int(video_id),
                    "name": video_data.get('creator_name', ''),
                    "slug": f"{video_data.get('creator_name', '').lower().replace(' ', '-')}-{video_id}",
                    "description": video_data.get('description', ''),
                    "video": item['video_url'],
                    "image": item.get('image', item['video_url']),
                    "user_id": int(video_data['user_id']),
                    "user_name": video_data.get('creator_name', ''),
                    "user_slug": video_data.get('creator_name', '').lower().replace(' ', '-'),
                    "avatar": f"https://media.talentpitch.co/users/{video_data['user_id']}/avatar-100.png",
                    "main_objective": "be_discovered",
                    "type_audience": "innovators",
                    "type_audiences": ["innovators"],
                    "interest_areas": [],
                    "role_objectives": [],
                    "connected": ""
                }

                all_items.append(resume_obj)
                resume_ids.append(str(video_id))

        tracker.track_video_view(user_id, video_id, item['video_url'], item['position'], item['patron_type'], session_id)

    if len(all_items) >= 50:
        background_tasks.add_task(async_flush_activity, user_id)

    mix_ids = [str(item['id']) for item in all_items]

    return {
        "statusCode": 200,
        "body": {
            "mix_ids": mix_ids,
            "items": all_items
        }
    }

@router.post("/api/search/discover")
async def discover(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint para descubrir resumes/videos (talentos).
    Retorna solo items que NO son tipo FW del feed generado por el motor de recomendacion.
    Implementa flush inteligente cuando se acumulan 50+ actividades.
    """
    data = await request.json()
    user_id = data.get('SELF_ID', data.get('user_id', 0))
    max_size = min(data.get('MAX_SIZE', data.get('size', 20)), 100)
    last_ids = data.get('LAST_IDS', data.get('videos_excluidos', []))
    session_id = data.get('session_id', None)

    if isinstance(last_ids, str) and last_ids:
        last_ids = [int(x) for x in last_ids.split(',') if x]

    recommendation_engine = get_recommendation_engine()
    tracker = ActivityTracker()
    data_service = get_data_service()

    tracker.track_feed_request(user_id, 'discover', {'size': max_size}, session_id)

    feed, metricas = recommendation_engine.generar_scroll_infinito(user_id, n_videos=24, videos_excluidos=last_ids, incluir_fw=False)

    resumes_items = []
    resume_ids = []

    for item in feed:
        if item['type'] != 'FW':
            video_id = item['video_id']
            video_row = data_service.videos_df[data_service.videos_df['id'] == video_id]

            if len(video_row) > 0:
                video_data = video_row.iloc[0]

                resume_obj = {
                    "type": "resume",
                    "id": int(video_id),
                    "name": video_data.get('creator_name', ''),
                    "slug": f"{video_data.get('creator_name', '').lower().replace(' ', '-')}-{video_id}",
                    "description": video_data.get('description', ''),
                    "video": item['video_url'],
                    "image": item.get('image', item['video_url']),
                    "user_id": int(video_data['user_id']),
                    "user_name": video_data.get('creator_name', ''),
                    "user_slug": video_data.get('creator_name', '').lower().replace(' ', '-'),
                    "avatar": f"https://media.talentpitch.co/users/{video_data['user_id']}/avatar-100.png",
                    "main_objective": "be_discovered",
                    "type_audience": "innovators",
                    "type_audiences": ["innovators"],
                    "interest_areas": [],
                    "role_objectives": [],
                    "connected": ""
                }

                resumes_items.append(resume_obj)
                resume_ids.append(str(video_id))

                tracker.track_video_view(user_id, video_id, item['video_url'], item['position'], item['type'], session_id)

    if len(resumes_items) >= 50:
        background_tasks.add_task(async_flush_activity, user_id)

    return {
        "statusCode": 200,
        "body": {
            "resume_ids": resume_ids,
            "items": resumes_items
        }
    }

@router.post("/api/search/flow")
async def flow(request: Request, background_tasks: BackgroundTasks):
    """
    Endpoint principal de feed mixto con patron VMP-AU-AU-VMP-NU-FW.
    Retorna challenges y resumes mezclados segun el algoritmo de bandits contextuales.
    Incluye metricas de rendimiento y diversidad.
    Implementa flush inteligente cuando se acumulan 50+ actividades.
    """
    data = await request.json()
    user_id = data.get('user_id', data.get('SELF_ID', 0))
    max_size = min(data.get('size', data.get('MAX_SIZE', 18)), 100)
    last_ids = data.get('videos_excluidos', data.get('LAST_IDS', []))
    session_id = data.get('session_id', None)

    if isinstance(last_ids, str) and last_ids:
        last_ids = [int(x) for x in last_ids.split(',') if x]

    recommendation_engine = get_recommendation_engine()
    tracker = ActivityTracker()
    data_service = get_data_service()

    tracker.track_feed_request(user_id, 'flow', {'size': max_size}, session_id)

    feed_result, metricas = recommendation_engine.generar_feed_flows_only(user_id, n_flows=24, excluded_ids=last_ids)

    all_items = []
    challenge_ids = []

    for item in feed_result:
        video_id = item['video_id']
        flow_data = item['flow_data']

        interest_areas = []
        try:
            if pd.notna(flow_data.get('interest_areas')):
                areas_data = json.loads(flow_data['interest_areas']) if isinstance(flow_data['interest_areas'], str) else flow_data['interest_areas']
                if isinstance(areas_data, list):
                    interest_areas = areas_data
        except:
            pass

        type_objectives = []
        try:
            if pd.notna(flow_data.get('type_objectives')):
                obj_data = json.loads(flow_data['type_objectives']) if isinstance(flow_data['type_objectives'], str) else flow_data['type_objectives']
                if isinstance(obj_data, list):
                    type_objectives = obj_data
        except:
            type_objectives = ["hire"]

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
            "user_avatar": f"https://media.talentpitch.co/users/{flow_data['user_id']}/avatar-100.png",
            "talent_type": flow_data.get('talent_type', 'innovators'),
            "interest_areas": interest_areas,
            "type_objectives": type_objectives,
            "top": True,
            "created_at": flow_data['created_at'].isoformat() if hasattr(flow_data['created_at'], 'isoformat') else str(flow_data['created_at']),
            "updated_at": datetime.now().isoformat()
        }

        if pd.notna(flow_data.get('status_at')):
            challenge_obj["status_at"] = str(flow_data['status_at'])

        all_items.append(challenge_obj)
        challenge_ids.append(str(video_id))

        tracker.track_video_view(user_id, video_id, flow_data['video'], item['position'], 'FW', session_id)

    if len(all_items) >= 50:
        background_tasks.add_task(async_flush_activity, user_id)

    return {
        "statusCode": 200,
        "body": {
            "challenge_ids": challenge_ids,
            "items": all_items
        }
    }

@router.post("/api/search/reload")
async def reload_data():
    """
    Recarga todos los datos desde MySQL y reinicializa el motor de recomendacion.
    Util para actualizar el catalogo sin reiniciar el servidor.
    """
    global _data_service_instance, _recommendation_engine_instance
    _data_service_instance = None
    _recommendation_engine_instance = None

    get_data_service()
    get_recommendation_engine()

    return {"statusCode": 200, "message": "Data reloaded successfully"}
