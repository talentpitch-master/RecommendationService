# TalentPitch Search Service

Servicio de recomendaciones y búsqueda de contenido basado en motor de bandits contextuales adaptativos. Proporciona feeds personalizados de videos y flows para usuarios de la plataforma TalentPitch.

## Arquitectura

### Stack Tecnológico

- Python 3.13 Alpine
- FastAPI + Gunicorn + Uvicorn
- MySQL (conexión directa)
- Redis (conexión directa con SSL)
- Docker

### Componentes Principales

- **Motor de Recomendaciones**: Bandits contextuales con múltiples pools (VMP, NU, AU, FLOWS, EXPLORE)
- **Data Service**: Carga y gestión de datos en memoria
- **Activity Tracker**: Registro de actividades de usuario en Redis con flush automático a MySQL
- **API REST**: Endpoints para descubrimiento de contenido y gestión de datos
- **Conexiones directas**: Sin tuneles SSH, conexión directa a MySQL y Redis

## Estructura del Proyecto

```
search/
├── api/
│   ├── endpoints.py       # Endpoints REST
│   └── server.py          # Configuración FastAPI
├── core/
│   ├── cache.py          # Conexión Redis con SSH tunnel
│   └── database.py       # Conexión MySQL con SSH tunnel
├── services/
│   ├── data_service.py   # Carga de datos en memoria
│   ├── recommendation.py # Motor de recomendaciones
│   └── tracking.py       # Tracking de actividades
├── utils/
│   └── logger.py         # Configuración de logs
├── credentials/
│   ├── .env              # Variables de entorno (no versionado)
│   ├── env.example       # Template de variables
│   └── *.pem             # Llaves SSH (no versionadas)
├── Dockerfile
├── requirements.txt
└── main.py
```

## Configuración

### Variables de Entorno

Archivo: `credentials/.env`

```ini
[MYSQL]
MYSQL_HOST=
MYSQL_PORT=
MYSQL_USER=
MYSQL_PASSWORD=
MYSQL_DB=

[REDIS]
REDIS_HOST=
REDIS_PASSWORD=
REDIS_PORT=
REDIS_SCHEME=

[API_CONFIG]
API_HOST=
API_PORT=

[FLUSH_CONFIG]
FLUSH_INTERVAL_SECONDS=
FLUSH_THRESHOLD_ACTIVITIES=
```

### Cambio de Ambiente

Para cambiar entre staging y production, simplemente edita el archivo `credentials/.env` con las credenciales correspondientes. No necesitas modificar múltiples variables con prefijos.

## Ejecutar localmente

```bash
# Ejecutar localmente
uvicorn main:app --reload --host 0.0.0.0 --port 5005
```

## Construcción y Despliegue

### Build Local

```bash
# Build de imagen
docker build -t talentpitch-search:latest .

# Build con plataforma específica (para producción)
docker build --platform linux/amd64 -t talentpitch-search:staging .
```

### Ejecución Local

**Contenedor estándar:**
```bash
docker run -d --name search-service \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  talentpitch-search:latest
```

**Contenedor "source" (configuración actual):**
```bash
# Detener y remover contenedor existente si existe
docker stop source && docker rm source

# Iniciar contenedor source
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  talentpitch-search:latest
```

**Volúmenes montados:**
- `credentials/`: Credenciales de acceso (read-only) - incluye .env y archivos .pem
- `data/`: Datos persistentes de la aplicación
- `logs/`: Logs de la aplicación

### Verificación de Estado

```bash
# Ver contenedores corriendo
docker ps

# Logs de contenedor
docker logs source
docker logs -f source  # Seguir logs en tiempo real

# Logs internos de aplicación
docker exec source cat /app/logs/talent.log

# Verificar que el servidor responde
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'
```

### Generar Archivos JSON de Ejemplo

Una vez el contenedor está corriendo, generar los archivos JSON con respuestas reales:

```bash
# Esperar a que el servidor inicie (60 segundos)
sleep 60

# Generar los 3 archivos JSON
curl -s -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}' | python -m json.tool > api/endpoint_total.json

curl -s -X POST http://localhost:5002/api/search/discover \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}' | python -m json.tool > api/endpoint_discover.json

curl -s -X POST http://localhost:5002/api/search/flow \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}' | python -m json.tool > api/endpoint_flow.json
```

### Gestión del Contenedor

```bash
# Detener contenedor
docker stop source

# Reiniciar contenedor
docker restart source

# Ver logs durante startup
docker logs -f source

# Remover contenedor
docker stop source && docker rm source

# Reconstruir imagen y reiniciar
docker build -t talentpitch-search:latest . && \
docker stop source && docker rm source && \
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e ENVIRONMENT=production \
  talentpitch-search:latest
```

## Seguridad

### Vulnerabilidades

La imagen Docker ha sido optimizada para tener 0 vulnerabilidades:

- Base: Python 3.13 Alpine
- pip versión: 25.3.dev0 (desde GitHub main branch)
- busybox actualizado desde edge repository
- Resultado Docker Scout: **0C 0H 0M 0L**

### Escaneo de Vulnerabilidades

```bash
docker scout quickview talentpitch-search:staging
```

## API Endpoints

Los siguientes 3 endpoints retornan recomendaciones personalizadas de contenido con estructura unificada. Ver archivos JSON con respuestas reales completas (usuario 2023354 - Dj Paul) en carpeta `api/`:

- **[api/endpoint_total.json](api/endpoint_total.json)** - Total Endpoint
- **[api/endpoint_discover.json](api/endpoint_discover.json)** - Discover Endpoint
- **[api/endpoint_flow.json](api/endpoint_flow.json)** - Flow Endpoint

### Estructura Simplificada de Respuesta

Cada endpoint retorna UNA SOLA lista de IDs según el tipo de contenido:

- **`/api/search/total`** → `mix_ids` (lista mezclada de 24 IDs)
- **`/api/search/discover`** → `resume_ids` (lista de 24 IDs de resumes)
- **`/api/search/flow`** → `challenge_ids` (lista de 24 IDs de challenges)

**Estructura general:**
```json
{
  "statusCode": 200,
  "body": {
    "mix_ids": [...],        // Solo en /total
    "resume_ids": [...],     // Solo en /discover
    "challenge_ids": [...],  // Solo en /flow
    "items": [...]           // Array de 24 objetos con datos completos
  }
}
```

**Campo `items`:**
- Cada item incluye campo `type: "challenge"` o `type: "resume"`
- Permite al frontend determinar el tipo de contenido
- Facilita el rendering de componentes según el tipo
- Los IDs en la lista corresponden al orden de items

---

### 1. POST /api/search/total

**Descripción:** Feed completo mezclando challenges y resumes (24 items). Combina contenido de VMP, AU, NU y FW. Soporta scroll infinito.

**Request:**
```bash
# Primera carga
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'

# Scroll infinito (excluyendo IDs ya vistos)
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354, "excluded_ids": [129279, 129447, 126491]}'
```

**Parámetros:**
- `user_id` (int, requerido): ID del usuario
- `excluded_ids` (array[int], opcional): IDs a excluir para scroll infinito
- Backward compatible: `LAST_IDS`, `videos_excluidos`

**Response:** Ver [api/endpoint_total.json](api/endpoint_total.json) para estructura completa

**Estructura de respuesta:**
```json
{
  "statusCode": 200,
  "body": {
    "mix_ids": ["129279", "496402", "129447", ...],  // 24 IDs mezclados
    "items": [
      {
        "id": 129279,
        "type": "resume",
        "user_id": 123,
        ...
      },
      {
        "id": 496402,
        "type": "challenge",
        "title": "Challenge Title",
        ...
      }
    ]
  }
}
```

---

### 2. POST /api/search/discover

**Descripción:** Feed de resumes (videos de talento) ordenados por relevancia. Solo contenido tipo resume de pools VMP, AU y NU.

**Request:**
```bash
curl -X POST http://localhost:5002/api/search/discover \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354, "size": 24}'
```

**Parámetros:**
- `user_id` (int, requerido): ID del usuario
- `size` (int, opcional): Cantidad de resumes (default: 24)
- `videos_excluidos` (array[int], opcional): IDs a excluir

**Response:** Ver [api/endpoint_discover.json](api/endpoint_discover.json) para estructura completa

**Estructura de respuesta:**
```json
{
  "statusCode": 200,
  "body": {
    "resume_ids": ["129279", "129447", "126491", ...],  // 24 IDs de resumes
    "items": [
      {
        "id": 129279,
        "type": "resume",
        "user_id": 123,
        ...
      }
    ]
  }
}
```

---

### 3. POST /api/search/flow

**Descripción:** Feed de challenges (flows y oportunidades). Solo contenido tipo challenge del pool FW.

**Request:**
```bash
curl -X POST http://localhost:5002/api/search/flow \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354, "size": 24}'
```

**Parámetros:**
- `user_id` (int, requerido): ID del usuario
- `size` (int, opcional): Total de items (default: 24)
- `excluded_ids` (array[int], opcional): IDs a excluir para scroll infinito

**Response:** Ver [api/endpoint_flow.json](api/endpoint_flow.json) para estructura completa

**Estructura de respuesta:**
```json
{
  "statusCode": 200,
  "body": {
    "challenge_ids": ["496402", "496389", "496386", ...],  // 24 IDs de challenges
    "items": [
      {
        "id": 496402,
        "type": "challenge",
        "title": "Challenge Title",
        ...
      }
    ]
  }
}
```

### POST /api/search/reload

Recarga todos los datos desde MySQL y reinicializa el motor de recomendaciones sin reiniciar el servidor.

**Response:**
```json
{
  "statusCode": 200,
  "message": "Data reloaded successfully"
}
```

## Sistema de Tracking

### Registro de Actividades

Las actividades de usuario se registran automáticamente en Redis cuando:
- Solicitan un feed (feed_request)
- Ven un video (video_view)

### Flush Automático

El sistema implementa flush automático de Redis a MySQL cuando:
- Se acumulan 50 o más actividades para un usuario
- Se ejecuta en background sin bloquear la respuesta

### Tabla MySQL

Las actividades se almacenan en la tabla `activity_log`:

```sql
activity_log (
  log_name,
  description,
  subject_id,
  subject_type,
  causer_id,      -- user_id
  causer_type,
  properties,     -- JSON con datos completos
  url,
  created_at,
  updated_at
)
```

## Datos Cargados en Memoria

Al iniciar, el servicio carga en memoria:

- Usuarios: ~198,000
- Videos: ~1,962
- Interacciones: ~20,000
- Conexiones sociales: ~26,000
- Flows: ~94

## Motor de Recomendaciones

### Pools de Contenido

- **VMP**: Videos más populares
- **NU**: Nuevos usuarios (onboarding)
- **AU**: Usuarios activos
- **FLOWS**: Challenges y oportunidades
- **EXPLORE**: Contenido de exploración

### Métricas del Feed

Cada feed generado incluye:
- Diversidad de creadores (target: 100%)
- Diversidad de skills (target: 60-75%)
- Cobertura de catálogo (27-28%)
- Contenido nuevo (25-35%)
- Tiempo de ejecución (<0.2s)

## CI/CD

### GitHub Actions Workflow

Archivo: `.github/workflows/search-deploy.yaml`

**Trigger:** Manual (workflow_dispatch)

**Inputs:**
- environment: staging o prod (default: staging)
- image_tag: Tag de la imagen Docker

**Proceso:**
1. Obtiene credenciales de AWS S3
2. Construye imagen Docker
3. Publica a Amazon ECR
4. Despliega a EKS en namespace correspondiente
5. Inyecta variable ENVIRONMENT en .env

### Despliegue Manual

```bash
# Desde GitHub UI:
# Actions > search-deploy > Run workflow
# Seleccionar environment: staging o prod
# Ingresar image_tag
```

## Monitoreo

### Health Check

El servicio responde en el puerto 5002. Verificar con:

```bash
curl http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "limit": 5}'
```

### Logs

Los logs se escriben en:
- Stdout/stderr del contenedor (gunicorn, uvicorn)
- `/app/logs/talent.log` (logs de aplicación)

Niveles de log importantes:
- INFO: Operaciones normales
- ERROR: Errores de conexión, queries fallidas

### Métricas Clave

- Tiempo de carga inicial: ~30-40 segundos
- Tiempo de respuesta por feed: 0.1-0.2 segundos
- Workers: 4 (configurado en gunicorn)
- Timeout de conexión MySQL: 30 segundos
- Timeout de lectura/escritura MySQL: 60 segundos

## Troubleshooting

### Error: Variables de entorno faltantes

Verificar que todas las variables requeridas estén en `credentials/.env`.

### Error: No se puede conectar a MySQL/Redis

Verificar:
1. Archivo de llave SSH existe en `credentials/talethpitch-develop-bastion.pem`
2. Permisos de llave SSH (debe ser 400 o 600)
3. Bastion host accesible desde el contenedor
4. Credenciales de MySQL/Redis correctas

### Performance degradado

1. Verificar logs por queries lentas
2. Revisar tamaño de datos cargados en memoria
3. Considerar incrementar workers de gunicorn
4. Verificar latencia de conexiones SSH tunnel

## Testing

### Script de Prueba Automática

Ejecutar: `python test_user_flow.py`

Valida:
- Generación de recomendaciones
- Tracking de actividades en Redis
- Auto-flush a MySQL
- Persistencia en tabla activity_log

### Prueba Manual con REST Client

Usar archivo: `test_user_navigation.http`

Requiere extensión REST Client en VS Code.

## Contacto y Soporte

Para incidencias o cambios, contactar al equipo de desarrollo o abrir un issue en el repositorio del proyecto.
