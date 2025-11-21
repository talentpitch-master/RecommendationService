# TalentPitch Recommendation Service - Documentation

Servicio de recomendaciones basado en bandits contextuales adaptativos para feeds personalizados de videos y flows.

## Quick Start

```bash
# Build
docker build -t talentpitch-search:latest .

# Run
docker run -d --name source -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  talentpitch-search:latest

# Test
curl -X POST http://localhost:5002/api/search/total \
  -H "Content-Type: application/json" \
  -d '{"user_id": 2023354}'
```

## Stack Tecnológico

- **Backend**: Python 3.13 Alpine + FastAPI + Gunicorn + Uvicorn
- **Database**: MySQL (SSH tunnel)
- **Cache**: Redis (SSL)
- **Algorithms**: Contextual Bandits (LinUCB)
- **Container**: Docker

## Documentación Organizada

### 01 - Setup

Configuración inicial y migración de ambientes.

- [migration_guide.md](01-setup/migration_guide.md) - Migración de variables de entorno

### 02 - Development

Guía de desarrollo y estándares de código.

- [guide.md](02-development/guide.md) - Setup local, debugging, testing
- [code_standards.md](02-development/code_standards.md) - Reglas de programación y estándares

### 03 - Architecture

Arquitectura del sistema y optimizaciones.

- [system_design.md](03-architecture/system_design.md) - Arquitectura, componentes, flujos de datos
- [database_optimization.md](03-architecture/database_optimization.md) - Optimización de índices MySQL
- [scalability_analysis.md](03-architecture/scalability_analysis.md) - Análisis de escalabilidad y HPA

### 04 - Deployment

Deployment y operaciones en producción.

- [production_guide.md](04-deployment/production_guide.md) - Deployment, Docker, producción

### 05 - References

Referencias y configuraciones adicionales.

- [ide_configuration.md](05-references/ide_configuration.md) - Configuración de Cursor IDE

## API Endpoints

| Endpoint | Descripción |
|----------|-------------|
| `POST /api/search/total` | Recomendaciones completas (videos + flows) |
| `POST /api/search/discover` | Solo videos |
| `POST /api/search/flow` | Solo flows |

## Configuración Básica

Variables de entorno en `credentials/.env`:

```ini
[MYSQL]
MYSQL_HOST=mysql-host.example.com
MYSQL_PORT=3306
MYSQL_USER=user
MYSQL_PASSWORD=pass
MYSQL_DB=database

[REDIS]
REDIS_HOST=redis-host.example.com
REDIS_PASSWORD=pass
REDIS_PORT=6379
REDIS_SCHEME=rediss

[SSH]
SSH_HOST=bastion-host.example.com
SSH_USER=ubuntu

[API_CONFIG]
API_HOST=0.0.0.0
API_PORT=5002

[FLUSH_CONFIG]
FLUSH_INTERVAL_SECONDS=900
FLUSH_THRESHOLD_ACTIVITIES=50
```

## Motor de Recomendaciones

Sistema de **Contextual Bandits (LinUCB)** con 5 pools:

1. **VMP** - Most Valued Products (contenido popular)
2. **NU** - New (contenido reciente <45 días)
3. **AU** - Affine to User (personalizado)
4. **FLOWS** - Challenges y oportunidades
5. **EXPLORE** - Exploración aleatoria

## Performance

- **Throughput**: 20.20 req/s (1 worker)
- **Latencia P95**: ~50ms
- **Carga de datos**: ~4.06s
- **videos_query**: 143ms (-21% optimizado)

## Troubleshooting

### Conexión a Base de Datos

```python
from utils.db_connect import get_db_connection

conn, tunnel = get_db_connection()
try:
    results = conn.execute_query("SELECT * FROM users LIMIT 1")
finally:
    conn.close()
    tunnel.stop_tunnel()
```

### Ver Logs

```bash
docker logs -f source
```

### Reiniciar

```bash
docker restart source
```

## Soporte

1. Revisar documentación correspondiente
2. Verificar [Troubleshooting](#troubleshooting)
3. Contactar equipo de desarrollo

---

**Última actualización**: 2025-11-20
**Versión**: 2.0
**Mantenedor**: TalentPitch Dev Team
