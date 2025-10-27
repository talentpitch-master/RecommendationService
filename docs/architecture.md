# Arquitectura del Sistema - TalentPitch Recommendation Service

## 📐 Arquitectura General

```
┌─────────────────────────────────────────────────────────────┐
│                        FastAPI Server                        │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Endpoints  │  │  Background  │  │  Middleware      │   │
│  │            │→ │  Tasks       │  │  (CORS, Flush)   │   │
│  └────────────┘  └──────────────┘  └──────────────────┘   │
└────────┬────────────────┬──────────────────┬────────────────┘
         │                │                  │
         │                │                  │
    ┌────▼────┐    ┌──────▼──────┐   ┌──────▼──────┐
    │  Data   │    │ Recommen-   │   │  Activity   │
    │ Service │    │ dation      │   │  Tracker    │
    │         │    │ Engine      │   │             │
    └────┬────┘    └──────┬──────┘   └──────┬──────┘
         │                │                  │
    ┌────▼────────────┬───▼──────────────────▼────┐
    │     In-Memory Data (Pandas DataFrames)      │
    │  users_df, videos_df, interactions_df,     │
    │  connections_df, flows_df, embeddings       │
    └────────────────┬────────────────────────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
    ┌────▼────┐ ┌───▼────┐  ┌──▼────┐
    │  MySQL  │ │  Redis │  │ Config│
    │ (SSH)   │ │ (SSH)  │  │       │
    └─────────┘ └────────┘  └───────┘
```

## 🔄 Ciclo de Vida de la Aplicación

### Startup

```
1. Load Config (.env)
   ├─ Set environment (staging/prod)
   ├─ Load credentials
   └─ Initialize paths

2. Establish Connections
   ├─ MySQL via SSH tunnel
   └─ Redis via SSH tunnel

3. Load Data (DataService)
   ├─ Query users, videos, interactions
   ├─ Load connections, flows
   ├─ Parse JSON fields
   └─ Normalize data

4. Initialize Recommendation Engine
   ├─ Build skill embeddings
   ├─ Construct social graph
   ├─ Pre-calculate advanced scores
   └─ Initialize bandits (VMP, AU, NU)

5. Setup FastAPI
   ├─ Register endpoints
   ├─ Setup CORS
   └─ Start background flush task

6. Ready to serve requests
```

### Request Flow

```
Client Request
     │
     ├─→ Parse parameters (user_id, excluded_ids)
     │
     ├─→ Get RecommendationEngine singleton
     │
     ├─→ Get user preferences (history, skills)
     │
     ├─→ Generate feed with bandits:
     │     ├─ VMP pool (popular)
     │     ├─ AU pool (personalized)
     │     ├─ NU pool (new)
     │     ├─ FW pool (flows)
     │     └─ EXPLORE pool (random)
     │
     ├─→ Apply diversity constraints
     │
     ├─→ Format response (mix_ids, items)
     │
     ├─→ Track activities in Redis
     │
     ├─→ Check flush threshold (50+ activities)
     │
     └─→ Return response to client
```

## 🧠 Motor de Recomendaciones

### Bandit Contextual Adaptativo

```python
class BanditContextualAdaptativo:
    - n_features: 18
    - alpha: parámetro de exploración
    - beta: parámetro de adaptación
    - A: matriz Ridge Regression (18x18)
    - b: vector de recompensas
    - theta: parámetros del modelo
    - A_inv: inversa de A para UCB
```

### LinUCB (Linear Upper Confidence Bound)

```
UCB = μ + α * √(x^T * A^(-1) * x) + β * varianza_adaptativa

Donde:
- μ = reward esperado (contexto * theta)
- α = nivel de exploración
- x = features del item
- A^(-1) = inversa de matriz Ridge
- β = adaptación según varianza
```

### Feature Engineering (18 features)

```python
features = np.zeros((n_candidatos, 18))

features[:, 0] = score_engagement          # Views + Rating + Connections
features[:, 1] = score_temporal            # Days since creation
features[:, 2] = score_calidad             # Rating quality gate
features[:, 3] = score_popularidad         # Popularity score
features[:, 4] = diversidad_skills         # Skill diversity
features[:, 5] = similitud_skills          # User-video skill match
features[:, 6] = match_extendido           # Match score (skills+knowledge+tools+langs)
features[:, 7] = coincidencia_ciudad       # City match
features[:, 8] = señales_sociales          # Social connections
features[:, 9] = log(views) / 10
features[:, 10] = rating / 5
features[:, 11] = rareza_skills            # Skill rarity
features[:, 12] = pasa_gate_calidad        # Quality gate
features[:, 13] = influencia_social         # Social influence
features[:, 14] = rating_count / max
features[:, 15] = like_count / max
features[:, 16] = exhibited_count / max
features[:, 17] = random_exploration       # Random boost
```

### Pool Selection Strategy

#### VMP (Valued Products)

**Parámetros**: α=1.5, β=0.8

**Selección**:
```python
1. Filter por gate de calidad
2. Calcular UCB score con bandit VMP
3. Combinar: UCB + engagement*2.2 + popularidad*1.6 + calidad*1.8
4. Boost contenido <45 días: +1.4
5. Weighted sampling de top candidatos
```

#### AU (Affine to User)

**Parámetros**: α=1.8, β=1.0

**Selección**:
```python
1. Calcular UCB score con bandit AU
2. Combinar: UCB + similitud_skills*2.8 + match_extendido*2.5
3. Boost contenido nuevo: +0.9
4. Return top N por score
```

#### NU (Nuevo)

**Parámetros**: α=2.5, β=1.3

**Selección**:
```python
1. Filter solo contenido <45 días
2. Calcular UCB score con bandit NU
3. Combinar: UCB + temporal*2.5 + diversidad*1.8 + rareza*1.4
4. Random exploration boost: +0.6
5. Sample aleatorio de top candidatos
```

#### FW (Flows)

**Selección**:
```python
1. Filter flows (no videos)
2. Score = random(0,40) + temporal*60
3. Sort by score
4. Return top N
```

## 🗄️ Modelo de Datos

### DataFrames en Memoria

#### users_df

```python
columns = [
    'id', 'name', 'city', 'country', 'created_at',
    'skills', 'languages', 'tools', 'knowledge',
    'hobbies', 'type_talentees', 'opencall_objective'
]
```

#### videos_df

```python
columns = [
    'id', 'user_id', 'video', 'views', 'video_skills',
    'video_knowledges', 'video_tools', 'video_languages',
    'role_objectives', 'created_at', 'description',
    'creator_city', 'creator_country', 'creator_name',
    'avg_rating', 'rating_count', 'connection_count',
    'like_count', 'exhibited_count', 'city',
    'days_since_creation', 'score_engagement',
    'score_temporal', 'boost_nuevo', 'score_calidad',
    'score_popularidad', 'diversidad_skills',
    'rareza_skills', 'pasa_gate_calidad'
]
```

#### interactions_df

```python
columns = [
    'user_id', 'video_id', 'rating',
    'created_at', 'interaction_type'
]
```

#### connections_df

```python
columns = [
    'user_id', 'connected_user_id', 'status', 'created_at'
]
```

#### flows_df

```python
columns = [
    'id', 'user_id', 'video', 'name', 'description',
    'created_at', 'creator_name', 'creator_city',
    'creator_country', 'city', 'days_since_creation'
]
```

## 🔄 Tracking y Flush

### Redis Keys

```
user_activity:{user_id}        # List of activities (TTL: 24h)
session:{user_id}:{timestamp}  # Session data (TTL: 1h)
```

### Activity Structure

```json
{
  "event_type": "video_view" | "feed_request",
  "user_id": int,
  "video_id": int,  # for video_view
  "video_url": str,
  "position": int,
  "feed_type": str,
  "timestamp": "ISO8601",
  "session_id": str
}
```

### Flush Process

```
1. Accumulate activities in Redis
   └─ LPUSH user_activity:{user_id} <activity_json>

2. Check flush conditions
   ├─ Activity count >= 50
   └─ Every 15 minutes (background task)

3. Transfer to MySQL
   ├─ Connect to MySQL
   ├─ For each activity in Redis:
   │   └─ INSERT INTO activity_log (...)
   └─ DELETE user_activity:{user_id}

4. Log result
   └─ Log inserted count
```

## 🔐 Seguridad

### SSH Tunnels

**MySQL Tunnel**:
```
Local App ←→ SSH Tunnel ←→ MySQL Server
  127.0.0.1:random   Bastion   10.x.x.x:3306
```

**Redis Tunnel**:
```
Local App ←→ SSH Tunnel ←→ Redis Server
  127.0.0.1:random   Bastion   10.x.x.x:6379
```

### Configuración

```python
# SSH Tunnel
tunnel = SSHTunnelForwarder(
    (ssh_host, 22),
    ssh_username=ssh_user,
    ssh_pkey=path_to_pem,
    remote_bind_address=(target_host, target_port),
    local_bind_address=('127.0.0.1', 0)  # random port
)
tunnel.start()

# MySQL Connection (via tunnel)
mysql_conn = pymysql.connect(
    host='127.0.0.1',
    port=tunnel.local_bind_port,
    user=mysql_user,
    password=mysql_password,
    db=mysql_db
)

# Redis Connection (via tunnel + SSL)
redis_client = redis.Redis(
    host='127.0.0.1',
    port=tunnel.local_bind_port,
    password=redis_password,
    ssl=(REDIS_SCHEME == 'tls'),
    db=1
)
```

## ⚡ Optimizaciones Implementadas

### 1. Pre-cálculo de Scores

- Calcular una vez al inicio
- Guardar en columnas de DataFrame
- Evitar re-computación en cada request

### 2. Embeddings de Skills

- Construir matriz de co-ocurrencia
- Normalizar embeddings
- Cache para lookups O(1)

### 3. Social Graph

- Pre-construir grafo en startup
- Calcular influencia social
- Lookups rápidos en recomendaciones

### 4. Vectorización

- Operaciones batch con NumPy
- Pandas vectorized operations
- Minimizar loops Python

### 5. Singleton Pattern

- Una instancia de cada servicio
- Reutilizar conexiones
- Reducir overhead

### 6. Connection Pooling

- Reutilizar conexiones SSH
- Cache de queries
- Close connections cuando sea necesario

## 📊 Métricas de Rendimiento

### Targets

| Métrica | Target | Actual |
|---------|--------|--------|
| Feed generation | < 0.2s | ~0.15s |
| Data reload | < 60s | ~35s |
| API response | < 0.3s | ~0.2s |
| Memory usage | < 1GB | ~600MB |
| Creator diversity | 100% | 100% |
| Skill diversity | 60-75% | ~65% |
| Catalog coverage | 25-35% | ~28% |
| New content ratio | 25-35% | ~30% |

### Escalabilidad

- **Horizontal**: Agregar workers (Gunicorn)
- **Vertical**: Aumentar memoria para más datos
- **Cache**: Redis ya implementado
- **DB**: Actualizar sin restart (reload endpoint)

## 🐛 Manejo de Errores

### Error Handling Levels

1. **Connection Errors**
   - Log error
   - Retry con backoff
   - Fallback a valores por defecto

2. **Data Errors**
   - Log warning
   - Skip item problemático
   - Continuar con resto

3. **Query Errors**
   - Log error
   - Return empty results
   - No fallar request completo

4. **Track Errors**
   - Log error
   - No bloquear respuesta
   - Reintentar en próximo flush

## 📈 Monitoring

### Logs

- **File**: `logs/talent.log`
- **Format**: `<timestamp> - <module> - <level> - <message>`
- **Timezone**: GMT-5
- **Rotation**: Manual (Docker volumes)

### Metrics to Track

- Response times
- Error rates
- Memory usage
- Database connection health
- Redis connection health
- Activities flushed count
- Bandit performance stats

## 🔧 Configuration Management

### Environment Variables

```python
# Load from credentials/.env
env_path = project_root / 'credentials' / '.env'
load_dotenv(env_path)

# Use simple variable names
mysql_host = os.getenv('MYSQL_HOST')
mysql_user = os.getenv('MYSQL_USER')
mysql_password = os.getenv('MYSQL_PASSWORD')
mysql_db = os.getenv('MYSQL_DB')
# ... etc
```

### Config Singleton

```python
class Config:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        # Load all env vars
```

## 🎯 Patrón de Recomendación

### Feed Pattern

```
PATRON: [VMP, AU, AU, VMP, NU, FW]
REPETICIONES: 4 veces = 24 items

Ejemplo de feed:
1.  VMP  - Video popular #1
2.  AU   - Video personalizado #1
3.  AU   - Video personalizado #2
4.  VMP  - Video popular #2
5.  NU   - Video nuevo
6.  FW   - Challenge
7.  VMP  - Video popular #3
8.  AU   - Video personalizado #3
...
24. FW   - Challenge
```

### Diversity Constraints

- **No repite creador**: Ventana deslizante de 12 items
- **No repite video**: Set de IDs usados
- **Diversidad skills**: Target 60-75%
- **Sin duplicados**: Check antes de agregar

---

**Última actualización**: 2025  
**Versión**: 2.0
