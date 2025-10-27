# TalentPitch Recommendation Service - Documentación Técnica

## 📋 Resumen Ejecutivo

Servicio de recomendación de contenido para la plataforma TalentPitch, implementando algoritmos de bandits contextuales adaptativos (LinUCB) para generar feeds personalizados de videos y challenges con capacidad de scroll infinito.

**Versión:** 2.0  
**Stack:** Python 3.13, FastAPI, Gunicorn, MySQL, Redis  
**Despliegue:** Docker (Alpine Linux)  
**Arquitectura:** Microservicio REST API

---

## 🏗️ Arquitectura

### Componentes Principales

1. **DataService** (Singleton)
   - Carga datos desde MySQL a DataFrames en memoria (~198k usuarios, ~1.9k videos)
   - Gestiona blacklist de URLs bloqueadas
   - Proporciona acceso rápido a datos con lookups O(1)

2. **RecommendationEngine** (Singleton)
   - Motor de bandits contextuales con algoritmo LinUCB
   - 5 pools de contenido: VMP, NU, AU, FLOWS, EXPLORE
   - Pre-cálculo de scores avanzados para optimización

3. **ActivityTracker** (Singleton)
   - Registro de actividades en Redis (TTL: 24h)
   - Auto-flush a MySQL cuando se acumulan 50+ actividades
   - Tracking de vistas y requests de feed

4. **Config** (Singleton)
   - Gestión centralizada de configuración
   - Variables de entorno multi-ambiente (staging/prod)
   - SSH tunnels para MySQL y Redis

### Flujo de Datos

```
Startup → Carga Datos MySQL → DataFrames en Memoria
   ↓
Request Usuario → Motor Recomendaciones → Bandits Contextuales
   ↓
Feed Personalizado → Tracking Redis → Auto-flush MySQL
```

### Patrones de Diseño

- **Singleton**: `Config`, `DataService`, `RecommendationEngine`, `MySQLConnection`, `RedisConnection`, `ActivityTracker`, `LoggerConfig`
- **Factory**: Inyección de dependencias para servicios
- **Strategy**: Algoritmos de recomendación por pool (VMP/AU/NU/FW/EXPLORE)

---

## 🧠 Algoritmo de Recomendaciones

### Sistema de Bandits Contextuales

Implementa **LinUCB** (Linear Upper Confidence Bound) para balancear exploración-explotación:

- **VMP** (Most Valued Products): α=1.5, β=0.8 (enfoque explotación)
- **AU** (Affine to User): α=1.8, β=1.0 (balanceado)
- **NU** (Nuevo): α=2.5, β=1.3 (prioriza exploración)

### Patrón de Feed

Orden repetido: **VMP-AU-AU-VMP-NU-FW** (6 slots, repetido 4 veces = 24 items)

- **VMP**: Contenido popular y valorado
- **AU**: Personalizado según skills del usuario
- **NU**: Contenido reciente (<45 días)
- **FW**: Challenges y oportunidades

### Features Contextuales (18 total)

1. Score engagement
2. Score temporal
3. Score calidad
4. Score popularidad
5. Diversidad skills
6. Similitud skills
7. Match extendido
8. Coincidencia ciudad
9. Señal social
10-18. Features adicionales de engagement

### Pre-cálculo de Scores

```python
score_engagement = views_norm * 0.35 + rating_norm * 0.40 + connections_norm * 0.25
score_temporal = exp(-days_since_creation / 28)
score_calidad = avg_rating * weight + log(connections) * 0.3
score_popularidad = log(views) * 0.40 + rating * 0.35 + log(connections) * 0.25
```

### Diversidad y Filtros

- **Diversidad de creadores**: 100% (no repite en 12 consecutivos)
- **Diversidad de skills**: 60-75% target
- **Cobertura catálogo**: 27-28%
- **Contenido nuevo**: 25-35%
- **Blacklist**: URLs bloqueadas desde `data/blacklist.csv`

---

## 📊 Datos y Fuentes

### Datos Cargados en Memoria

| Tipo | Cantidad Aprox. | Fuente |
|------|-----------------|--------|
| Usuarios | ~198,000 | `users` + `profiles` |
| Videos/Resumes | ~1,962 | `resumes` (status='send') |
| Interacciones | ~20,000 | `team_feedbacks`, `likes`, `matches` |
| Conexiones | ~26,000 | `user_connections` |
| Flows | ~94 | `challenges` (status='published') |

### Filtros de Calidad

Videos deben pasar gate de calidad:
- `avg_rating >= 3.0` O
- `views >= 20` O
- `connection_count >= 2` O
- `rating_count >= 2`

### Blacklist

Archivo: `data/blacklist.csv`
- URLs bloqueadas a nivel SQL
- Se aplica en queries para videos y flows
- Se carga al inicio del servicio

---

## 🔌 API Endpoints

### 1. POST /api/search/total

**Descripción:** Feed completo mezclando challenges y resumes (24 items)

**Request:**
```json
{
  "user_id": 2023354,
  "excluded_ids": [129279, 129447]
}
```

**Response:**
```json
{
  "statusCode": 200,
  "body": {
    "mix_ids": ["129279", "496402", ...],
    "items": [
      {"type": "resume", "id": 129279, ...},
      {"type": "challenge", "id": 496402, ...}
    ]
  }
}
```

**Parámetros compatibles:**
- `user_id` / `SELF_ID`
- `excluded_ids` / `LAST_IDS` / `videos_excluidos`

### 2. POST /api/search/discover

**Descripción:** Solo resumes/videos de talento (24 items)

**Request:**
```json
{
  "user_id": 2023354,
  "size": 24,
  "videos_excluidos": [129279]
}
```

**Response:**
```json
{
  "statusCode": 200,
  "body": {
    "resume_ids": ["129279", "129447", ...],
    "items": [{"type": "resume", ...}]
  }
}
```

### 3. POST /api/search/flow

**Descripción:** Solo challenges/flows (24 items)

**Request:**
```json
{
  "user_id": 2023354,
  "size": 24,
  "excluded_ids": [496402]
}
```

**Response:**
```json
{
  "statusCode": 200,
  "body": {
    "challenge_ids": ["496402", "496389", ...],
    "items": [{"type": "challenge", ...}]
  }
}
```

### 4. POST /api/search/reload

**Descripción:** Recarga datos desde MySQL sin reiniciar

**Response:**
```json
{
  "statusCode": 200,
  "message": "Data reloaded successfully"
}
```

---

## 🔄 Sistema de Tracking

### Actividades Registradas

1. **feed_request**: Solicitud de feed
   - Endpoint llamado
   - Parámetros enviados
   - Timestamp

2. **video_view**: Vista de video
   - Video ID visto
   - Posición en feed
   - Tipo de feed
   - URL del video

### Almacenamiento

- **Redis**: Actividades con TTL 24h, sesiones con TTL 1h
- **MySQL**: Tabla `activity_log` con estructura:
  ```sql
  activity_log (
    log_name,
    description,
    subject_id,
    subject_type,
    causer_id,      -- user_id
    causer_type,
    properties,     -- JSON con datos
    url,
    created_at,
    updated_at
  )
  ```

### Auto-Flush

Se ejecuta automáticamente cuando:
1. Usuario acumula 50+ actividades
2. Han pasado 15 minutos (tarea background)
3. Se llama manualmente

---

## 🔐 Seguridad

### SSH Tunnels

**MySQL Tunnel:**
```python
SSHTunnelForwarder(
    (ssh_host, 22),
    ssh_username=ssh_user,
    ssh_pkey=path_to_key,
    remote_bind_address=(mysql_host, mysql_port),
    local_bind_address=('127.0.0.1', 0)
)
```

**Redis Tunnel:**
- Similar a MySQL
- Configuración SSL según `REDIS_SCHEME` (tls/redis)

### Credenciales

- `.env` en carpeta `credentials/` (NO versionado)
- Llaves SSH `.pem` en carpeta `credentials/` (NO versionado)
- Soporte multi-ambiente: `STG_*` para staging, `PROD_*` para producción
- Selección mediante variable `ENVIRONMENT`

---

## 🐳 Docker

### Imagen

- **Base**: `python:3.13-alpine3.22`
- **Plataforma**: `linux/amd64`
- **Workers**: 4 (Gunicorn)
- **Timeout**: 120s
- **Puerto**: 5002

### Build

```bash
docker build --platform linux/amd64 -t talentpitch-search:latest .
```

### Run

```bash
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data:ro \
  -v $(pwd)/logs:/app/logs \
  -e ENVIRONMENT=production \
  talentpitch-search:latest
```

### Volúmenes

- `credentials/`: Credenciales (read-only)
- `data/`: Datos persistentes (read-only)
- `logs/`: Logs de aplicación

---

## 📁 Estructura de Archivos

```
RecommendationService/
├── api/
│   ├── endpoints.py         # FastAPI endpoints
│   ├── server.py            # Configuración FastAPI
│   └── endpoint_*.json      # Ejemplos de respuesta
├── core/
│   ├── cache.py             # Conexión Redis
│   ├── config.py            # Configuración singleton
│   └── database.py          # Conexión MySQL
├── services/
│   ├── data_service.py      # Carga de datos
│   ├── recommendation.py    # Motor bandits
│   └── tracking.py          # Activity tracker
├── utils/
│   └── logger.py            # Configuración logging
├── data/
│   └── blacklist.csv        # URLs bloqueadas
├── credentials/             # .env y keys (NO versionado)
├── logs/                    # Logs (NO versionado)
├── docs/                    # Documentación
├── .cursorrules            # Cursor IDE rules
├── Dockerfile              # Build container
├── docker-compose.yml      # Local development
├── main.py                 # Entry point
├── requirements.txt        # Dependencias
└── README.md               # Documentación usuario
```

---

## 📝 Convenciones de Código

### Python

- **Docstrings**: Español con triple comillas
- **Naming**: snake_case
- **Type hints**: Donde sea aplicable
- **Comentarios**: Español para explicar lógica compleja

### Imports

Orden estándar:
```python
# stdlib
import os
import sys
import time
import json

# third-party
import pandas as pd
import numpy as np
from fastapi import FastAPI

# local
from core.config import Config
from utils.logger import LoggerConfig
```

### Docstrings

```python
def funcion_ejemplo(parametro1, parametro2):
    """
    Descripcion breve de la funcion.
    
    Args:
        parametro1 (type): Descripcion
        parametro2 (type): Descripcion
    
    Returns:
        (type): Descripcion del retorno
    
    Notes:
        Consideraciones importantes
    """
    pass
```

### Logging

- **Formato**: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- **Timezone**: GMT-5 (Colombia)
- **Archivo**: `logs/talent.log`
- **Niveles**: INFO para operaciones normales, ERROR para fallos

```python
logger = LoggerConfig.get_logger(__name__)
logger.info("Operación exitosa")
logger.error("Error: {e}")
```

---

## ⚡ Performance

### Métricas Objetivo

- **Feed generation**: < 0.2s
- **Data reload**: ~30-40s
- **API response**: < 0.3s
- **Memory usage**: ~500MB-1GB (datos en memoria)

### Optimizaciones

1. **Pre-cálculo**: Scores avanzados calculados al inicio
2. **Vectorización**: Pandas/NumPy para operaciones batch
3. **Cache**: Diccionarios para lookups O(1)
4. **Batch processing**: Operaciones en lote
5. **Minimizar copias**: Solo usar `.copy()` cuando sea necesario

### DataFrame Best Practices

```python
# Filter and copy
candidatos = self.videos_df[
    (~self.videos_df['id'].isin(ids_excluir)) &
    (self.videos_df['pasa_gate_calidad'] == 1)
].copy()

# Vectorized operations
candidatos['score'] = (
    candidatos['views'] * 0.4 +
    candidatos['rating'] * 0.3 +
    candidatos['score_temporal'] * 0.3
)

# Sample with weights
indices = np.random.choice(len(df), size=n, p=weights, replace=False)
```

---

## 🧪 Testing

### Verificación Manual

```bash
# Health check
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'

# Ver logs
docker logs source
tail -f logs/talent.log

# Reload data
curl -X POST http://localhost:5002/api/search/reload
```

### Testing de Flujo

1. Cargar datos iniciales
2. Generar feed para usuario
3. Verificar tracking en Redis
4. Auto-flush a MySQL
5. Verificar persistencia en `activity_log`

---

## 🔧 Configuración de Ambientes

### Variables de Entorno

Archivo: `credentials/.env`

```ini
# Ambiente
ENVIRONMENT=staging  # o prod

# SSH Tunnel
SSH_HOST=<host>
SSH_USER=<user>

# Redis
REDIS_HOST=<host>
REDIS_PASSWORD=<pass>
REDIS_PORT=<port>
REDIS_SCHEME=tls  # o redis

# MySQL Staging
STG_MYSQL_HOST=<host>
STG_MYSQL_PORT=3306
STG_MYSQL_USER=<user>
STG_MYSQL_PASSWORD=<pass>
STG_MYSQL_DB=<db>

# MySQL Production
PROD_MYSQL_HOST=<host>
PROD_MYSQL_PORT=3306
PROD_MYSQL_USER=<user>
PROD_MYSQL_PASSWORD=<pass>
PROD_MYSQL_DB=<db>

# API
API_HOST=0.0.0.0
API_PORT=5002

# Flush
FLUSH_INTERVAL_SECONDS=900
FLUSH_THRESHOLD_ACTIVITIES=50
```

### Cambio de Ambiente

1. Modificar `ENVIRONMENT` en `.env`
2. Verificar credenciales correspondientes (STG_* o PROD_*)
3. Reconstruir imagen Docker
4. Reiniciar contenedor

---

## 📈 Monitoreo

### Health Check

Endpoint raíz:
```bash
curl http://localhost:5002/
# {"message": "TalentPitch Search API", "status": "ok", "version": "2.0"}
```

### Logs

```bash
# Docker logs
docker logs -f source

# Application logs
cat logs/talent.log
tail -f logs/talent.log
```

### Métricas Key

- Tiempo de carga inicial: ~30-40s
- Tiempo de respuesta por feed: 0.1-0.2s
- Workers activos: 4 (Gunicorn)
- Timeout conexión: 30s (MySQL), 10s (Redis)

---

## 🚀 Deployment

### Build Production

```bash
docker build --platform linux/amd64 -t talentpitch-search:prod .
```

### Run Production

```bash
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data:ro \
  -v $(pwd)/logs:/app/logs \
  -e ENVIRONMENT=production \
  talentpitch-search:prod
```

### Verificación

```bash
# Check container
docker ps | grep source

# Check logs
docker logs source

# Test endpoint
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'
```

---

## 🐛 Troubleshooting

### Error: Variables faltantes

Verificar que todas las variables estén en `.env` y el prefijo coincida con `ENVIRONMENT`.

### Error: Conexión SSH

Verificar:
1. Archivo `.pem` existe en `credentials/`
2. Permisos del archivo (600 o 400): `chmod 600 credentials/*.pem`
3. Bastion host accesible
4. Credenciales correctas

### Performance degradado

1. Revisar logs por queries lentas
2. Verificar tamaño de datos en memoria
3. Considerar aumentar workers de Gunicorn
4. Verificar latencia de SSH tunnels

### No hay recomendaciones

1. Verificar que datos se cargaron correctamente
2. Revisar gate de calidad
3. Verificar blacklist
4. Revisar logs para errores

---

## 📚 Referencias

### Repositorios

- **Main repo**: TalentPitch internal
- **Documentación**: README.md en raíz del proyecto
- **Cursor rules**: .cursorrules

### Algoritmos

- **LinUCB**: Linear Upper Confidence Bound para bandits contextuales
- **Collaborative Filtering**: Basado en interacciones usuario-video
- **Content-based**: Basado en skills, tools, languages
- **Social Signals**: Red social de conexiones

### Tecnologías

- **FastAPI**: https://fastapi.tiangolo.com/
- **Gunicorn**: https://gunicorn.org/
- **Pandas**: https://pandas.pydata.org/
- **SSH Tunnel**: https://github.com/pahaz/sshtunnel

---

## 📝 Changelog

### v2.0 (Current)

- ✅ Sistema de bandits contextuales adaptativos
- ✅ Auto-flush inteligente a MySQL
- ✅ Support multi-ambiente (staging/prod)
- ✅ Scroll infinito con exclusion de IDs
- ✅ Blacklist de URLs
- ✅ Tracking de actividades en Redis
- ✅ Diversidad de creadores garantizada
- ✅ Pre-cálculo de scores avanzados
- ✅ Zero vulnerabilidades (Docker Scout)

---

## 👥 Contributing

### Git Workflow

Commits usando Conventional Commits en inglés:

- `feat:` - Nueva feature
- `fix:` - Bug fix
- `refactor:` - Refactorización
- `docs:` - Documentación
- `perf:` - Performance
- `test:` - Tests

**Ejemplo:**
```bash
feat: add contextual bandits with LinUCB algorithm
fix: resolve Redis connection timeout issues
refactor: optimize DataFrame operations
```

### Code Review

- Verificar que siga convenciones
- Tests pasan
- No introduce vulnerabilidades
- Logs apropiados
- Documentación actualizada

---

## 📧 Contacto

Para incidencias o cambios, contactar al equipo de desarrollo o abrir un issue en el repositorio del proyecto.

---

**Última actualización:** 2025  
**Versión:** 2.0  
**Mantenedor:** TalentPitch Dev Team
