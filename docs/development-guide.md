# Guía de Desarrollo - TalentPitch Recommendation Service

## 🚀 Inicio Rápido

### Prerrequisitos

- Python 3.13+
- Docker
- Acceso a credenciales (`.env` y `.pem`)

### Setup Local

1. **Clonar repositorio**
```bash
git clone <repo-url>
cd RecommendationService
```

2. **Configurar credenciales**
```bash
# Copiar template
cp credentials/env.example credentials/.env

# Editar .env con tus credenciales
nano credentials/.env

# Agregar llave SSH
# Colocar talethpitch-develop-bastion.pem en credentials/
```

3. **Build y Run**
```bash
# Build image
docker build -t talentpitch-search:latest .

# Run container
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data:ro \
  -v $(pwd)/logs:/app/logs \
  talentpitch-search:latest

# Ver logs
docker logs -f source
```

4. **Verificar funcionamiento**
```bash
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'
```

---

## 🛠️ Desarrollo Local

### Sin Docker

```bash
# Instalar dependencias
pip install -r requirements.txt

# Ejecutar
python main.py
```

### Modo Debug

En `main.py`:
```python
uvicorn.run(
    "api.server:app",
    host="0.0.0.0",
    port=5002,
    reload=True,  # Auto-reload en cambios
    log_level="debug"
)
```

### Hot Reload

Si modificas código en `api/`, `core/`, `services/` o `utils/`:
- Los cambios se recargan automáticamente
- No necesitas reiniciar el servidor

---

## 📝 Convenciones de Desarrollo

### Estructura de Archivos

```
api/
  ├── endpoints.py       # Definir endpoints aquí
  ├── server.py          # Configuración FastAPI
  └── __init__.py

core/
  ├── config.py          # Configuración
  ├── database.py        # MySQL connection
  ├── cache.py           # Redis connection
  └── __init__.py

services/
  ├── data_service.py    # Carga de datos
  ├── recommendation.py  # Motor bandits
  ├── tracking.py        # Activity tracker
  └── __init__.py

utils/
  ├── logger.py          # Logging
  └── __init__.py
```

### Nomenclatura

**Archivos**: `snake_case.py`
- `data_service.py`
- `recommendation_engine.py`
- `activity_tracker.py`

**Clases**: `PascalCase`
- `DataService`
- `RecommendationEngine`
- `ActivityTracker`

**Funciones**: `snake_case`
- `load_all_data()`
- `get_user_history()`
- `generate_recommendations()`

**Constantes**: `UPPER_SNAKE_CASE`
- `MAX_VIDEOS = 24`
- `FLUSH_THRESHOLD = 50`

**Variables**: `snake_case`
- `user_id`
- `videos_df`
- `excluded_ids`

### Docstrings

**Formato estándar**:

```python
def funcion_ejemplo(parametro1, parametro2):
    """
    Descripcion breve de la funcion en una linea.
    
    Descripcion detallada si es necesaria para explicar
    logica compleja o comportamiento especial.
    
    Args:
        parametro1 (tipo): Descripcion del parametro
        parametro2 (tipo): Descripcion del parametro
    
    Returns:
        tipo: Descripcion del valor de retorno
        
    Raises:
        ValueError: Cuando parametro1 es invalido
        
    Example:
        >>> funcion_ejemplo(1, "test")
        {'resultado': 'success'}
        
    Notes:
        Consideraciones especiales o warnings
    """
    pass
```

### Comentarios

```python
# ✅ Correcto
# Calcular score de popularidad combinando views, ratings y connections
score = views_norm * 0.4 + rating_norm * 0.3 + connections_norm * 0.3

# ❌ Incorrecto
# calcula score
score = views_norm * 0.4 + rating_norm * 0.3 + connections_norm * 0.3

# ✅ Correcto - Inline comment para aclarar
if len(candidatos) == 0:  # Si no hay candidatos, usar pool de exploracion
    pool = self._seleccionar_boost_exploracion(ids_excluir)

# ❌ Incorrecto - Comentario obvio
# si candidatos es 0
if len(candidatos) == 0:
```

### Imports

**Orden requerido**:
1. Standard library
2. Third-party packages
3. Local modules

```python
# ✅ Correcto
import os
import sys
import time
import json

import pandas as pd
import numpy as np
from fastapi import FastAPI, Request

from core.config import Config
from services.data_service import DataService
from utils.logger import LoggerConfig
```

### Logging

```python
from utils.logger import LoggerConfig

logger = LoggerConfig.get_logger(__name__)

# INFO - Operaciones normales
logger.info(f"Generando feed para usuario {user_id}")

# WARNING - Situaciones inesperadas pero manejables
logger.warning(f"No se encontraron videos para usuario {user_id}, usando pool de exploracion")

# ERROR - Errores que requieren atención
logger.error(f"Error conectando a Redis: {e}")

# DEBUG - Información detallada para debugging
logger.debug(f"Pools generados: VMP={len(vmp_pool)}, AU={len(au_pool)}")
```

**Reglas**:
- No logear información sensible (passwords, tokens)
- Incluir contexto relevante en mensajes
- Usar f-strings para interpolación

---

## 🧪 Testing

### Test Manual de Endpoints

```bash
# Total endpoint
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'

# Discover endpoint
curl -X POST http://localhost:5002/api/search/discover \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354, "size": 24}'

# Flow endpoint
curl -X POST http://localhost:5002/api/search/flow \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354, "size": 24}'

# Reload endpoint
curl -X POST http://localhost:5002/api/search/reload
```

### Verificar Tracking

```python
# En Python interpreter o script
import redis

redis_client = redis.Redis(host='localhost', port=6379, db=1)

# Ver actividades de usuario
activities = redis_client.lrange(f"user_activity:{user_id}", 0, -1)
for activity in activities:
    print(activity)
```

### Verificar Flush

```sql
-- En MySQL
SELECT * FROM activity_log 
WHERE causer_id = 2023354 
ORDER BY created_at DESC 
LIMIT 10;
```

### Test de Performance

```python
import time
import requests

start = time.time()
response = requests.post(
    "http://localhost:5002/api/search/total",
    json={"user_id": 2023354}
)
elapsed = time.time() - start

print(f"Response time: {elapsed:.3f}s")
print(f"Status: {response.status_code}")
```

---

## 🔧 Debugging

### Ver Logs

```bash
# Logs en tiempo real
docker logs -f source

# Últimas 100 líneas
docker logs --tail 100 source

# Logs de aplicación
tail -f logs/talent.log
```

### Debug SQL Queries

En `services/data_service.py`:
```python
def _execute_query(self, query, params=None):
    logger.debug(f"Ejecutando query: {query[:100]}...")  # Log query
    results = self._conn.execute_query(query, params)
    logger.debug(f"Resultados: {len(results)} filas")
    return results
```

### Debug Redis

```python
# En código Python
logger.debug(f"Tracking video view: user={user_id}, video={video_id}")
```

### Inspeccionar DataFrames

```python
# En `services/data_service.py` después de cargar datos
logger.info(f"Videos cargados: {len(self.videos_df)}")
logger.info(f"Columnas: {list(self.videos_df.columns)}")
logger.info(f"Primeras filas:\n{self.videos_df.head()}")
```

### Profiling

```python
import cProfile

# Profilar función
profiler = cProfile.Profile()
profiler.enable()

# Tu código aquí
feed, metricas = engine.generar_scroll_infinito(user_id, 24)

profiler.disable()
profiler.print_stats(sort='cumulative')
```

---

## 🐛 Common Issues

### Error: "No se encontró .env"

**Problema**: Falta archivo `.env` en `credentials/`

**Solución**:
```bash
mkdir -p credentials
cp credentials/env.example credentials/.env
# Editar .env con credenciales reales
```

### Error: "Permission denied" en .pem

**Problema**: Permisos incorrectos en llave SSH

**Solución**:
```bash
chmod 600 credentials/*.pem
```

### Error: "Connection refused" MySQL/Redis

**Problema**: Tunnel SSH no conecta

**Solución**:
1. Verificar que bastion host es accesible
2. Verificar que llave SSH es correcta
3. Revisar variables de entorno
4. Ver logs: `docker logs source | grep -i error`

### Error: "MemoryError"

**Problema**: Datos muy grandes para memoria

**Solución**:
1. Reducir cantidad de datos cargados
2. Aumentar límite de memoria Docker
3. Optimizar queries SQL

### Feed vacío

**Problema**: No retorna recomendaciones

**Solución**:
1. Verificar que `pasa_gate_calidad` filtra correctamente
2. Verificar blacklist
3. Revisar logs para warnings
4. Verificar que usuario tiene interacciones

---

## 📦 Git Workflow

### Crear Nueva Feature

```bash
# 1. Crear branch
git checkout -b feat/nueva-funcionalidad

# 2. Hacer cambios
# ... edit code ...

# 3. Commit
git add .
git commit -m "feat: add nueva funcionalidad de recomendacion"

# 4. Push
git push origin feat/nueva-funcionalidad

# 5. Crear PR en GitHub
```

### Commit Messages

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add support for multiple bandit algorithms
fix: resolve Redis connection timeout
refactor: optimize DataFrame operations in recommendation engine
docs: update API documentation
perf: improve feed generation speed by 50%
test: add unit tests for bandit selection
chore: update dependencies

# Scope (opcional)
feat(api): add reload endpoint
fix(redis): handle connection errors gracefully

# Breaking changes
feat!: change API response format
BREAKING CHANGE: mix_ids is now required field
```

### Branch Naming

```
feat/nombre-funcionalidad
fix/nombre-bug
refactor/nombre-refactoring
docs/nombre-documentacion
perf/nombre-optimizacion
test/nombre-test
```

### Code Review Checklist

- [ ] Código sigue convenciones del proyecto
- [ ] Docstrings completos
- [ ] No hay credenciales hardcoded
- [ ] Logs apropiados
- [ ] Manejo de errores implementado
- [ ] Performance no degradado
- [ ] Tests pasan (si aplicable)
- [ ] README actualizado

---

## 🚀 Deployment

### Build Production

```bash
docker build --platform linux/amd64 \
  -t talentpitch-search:prod \
  -t talentpitch-search:latest \
  .
```

### Tag y Push

```bash
# Tag
docker tag talentpitch-search:prod \
  registry.example.com/talentpitch-search:prod

# Push
docker push registry.example.com/talentpitch-search:prod
```

### Deploy

```bash
# Obtener credenciales
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# Desplegar
kubectl set image deployment/search-api \
  search-api=registry.example.com/talentpitch-search:prod

# Verificar
kubectl rollout status deployment/search-api
```

### Rollback

```bash
kubectl rollout undo deployment/search-api
```

---

## 📊 Monitoring

### Health Check

```bash
curl http://localhost:5002/
# {"message": "TalentPitch Search API", "status": "ok", "version": "2.0"}
```

### Métricas Key

- Response time
- Error rate
- Memory usage
- Database connection pool
- Redis connection health
- Activities flushed

### Alertas

Configurar alertas para:
- Response time > 1s
- Error rate > 5%
- Memory usage > 80%
- Failed database connections
- Failed Redis connections

---

## 📚 Recursos

### Documentación del Proyecto

- [Resumen del Proyecto](project-summary.md)
- [Arquitectura](architecture.md)
- [README](../README.md)
- [Cursor Rules](../.cursorrules)

### Referencias Externas

- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Pandas Docs](https://pandas.pydata.org/)
- [NumPy Docs](https://numpy.org/)
- [SSH Tunnel](https://github.com/pahaz/sshtunnel)

### Algoritmos

- [LinUCB Paper](https://arxiv.org/abs/1003.0146)
- [Contextual Bandits](https://en.wikipedia.org/wiki/Multi-armed_bandit#Contextual_bandits)

---

## 🤝 Contributing

### Cómo Contribuir

1. Fork el repositorio
2. Crear branch para tu feature (`git checkout -b feat/amazing-feature`)
3. Commit tus cambios (`git commit -m 'feat: add amazing feature'`)
4. Push al branch (`git push origin feat/amazing-feature`)
5. Abrir Pull Request

### Coding Standards

- Seguir convenciones de nomenclatura
- Escribir docstrings completos
- Incluir logs apropiados
- Manejar errores graciosamente
- No hardcodear credenciales
- Optimizar para performance

### Issues

Antes de abrir un issue:
1. Buscar si ya existe
2. Verificar que no sea duplicado
3. Proporcionar información completa (logs, error messages, etc.)

---

**Última actualización**: 2025  
**Versión**: 2.0
