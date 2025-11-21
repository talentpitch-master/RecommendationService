# Guia de Deployment Completa - Escalamiento a 10K Usuarios/Hora

## Resumen Ejecutivo

Este documento describe el proceso completo de deployment para escalar el sistema de recomendaciones de 20 req/s a 240-300 req/s, soportando 10,000 usuarios/hora con amplio margen de seguridad.

### Mejoras Implementadas

| Fase | Cambio | Impacto | Throughput Esperado |
|------|--------|---------|-------------------|
| Inicial | - | - | 20 req/s |
| Fase 1 | Indices MySQL | +200% | 60 req/s |
| Fase 2 | Connection Pooling | +100% | 120 req/s |
| Fase 3 | Gunicorn 8 workers | +100-150% | 240-300 req/s |

### Capacidad Final

- Throughput: 240-300 req/s
- Latencia P95: < 150ms
- Usuarios/hora soportados: 864K - 1.08M
- Margen para 10K usuarios/hora: 31-39x

---

## Prerequisitos Generales

### Accesos Requeridos

- Usuario MySQL con privilegios CREATE INDEX y SELECT
- Acceso SSH a servidor de BD (o conexion directa)
- Acceso a servidor de aplicacion
- Permisos sudo en servidor de aplicacion (para instalar dependencias)

### Verificaciones Pre-Deployment

1. Backup de base de datos < 24 horas
2. Espacio en disco: 30% libre en servidor de BD
3. Version MySQL: 5.7+ o MariaDB 10.2+
4. Python: 3.10+
5. RAM servidor aplicacion: 8GB minimo
6. CPU servidor aplicacion: 4 vCPU minimo

### Tiempos Estimados

- Fase 1 (Indices): 30-60 minutos
- Fase 2 (Pooling): 15-30 minutos
- Fase 3 (Gunicorn): 15-30 minutos
- Tests y validacion: 30-60 minutos
- Total: 2-3 horas

---

## Fase 1: Indices MySQL

### Objetivo

Reducir tiempo de queries principales mediante indices estrategicos.

### Documentacion Detallada

Ver: [docs/database/phase1_deployment_guide.md](database/phase1_deployment_guide.md)

### Resumen de Pasos

1. Conectar a MySQL (produccion)
2. Ejecutar validacion pre-deployment: `migrations/phase1_validate.sql`
3. Guardar baseline de performance: `migrations/phase1_analyze_performance.sql`
4. Ejecutar creacion de indices: `migrations/phase1_create_indexes.sql`
5. Actualizar estadisticas: `ANALYZE TABLE <tablas>`
6. Validar indices creados: `migrations/phase1_validate.sql`
7. Medir performance post-indices: `migrations/phase1_analyze_performance.sql`
8. Validar mejoras:
   - users_query < 100ms
   - videos_query < 80ms
   - views_query < 70ms

### Rollback

Si hay problemas: `migrations/phase1_rollback.sql`

### Validacion de Exito

```bash
# En servidor de aplicacion
.venv/bin/python test_load_performance.py
```

Metricas esperadas:
- Throughput > 50 req/s
- users_query < 100ms
- videos_query < 80ms

---

## Fase 2: Connection Pooling

### Objetivo

Reutilizar conexiones MySQL para eliminar overhead de crear/cerrar conexiones.

### Cambios en Codigo

Archivo modificado: `core/database.py`

Cambios:
- Clase `ConnectionPool` agregada (thread-safe con Queue)
- Metodo `connect()` actualizado para usar pooling
- Metodo `close()` devuelve conexiones al pool
- Pool de 20 conexiones por default

### Deployment

NO requiere cambios en base de datos.

Pasos:
1. Actualizar codigo en servidor de aplicacion (git pull o deploy)
2. Verificar que archivo `core/database.py` tiene cambios
3. Reiniciar aplicacion

### Configuracion MySQL Requerida

En archivo de configuracion MySQL (my.cnf o RDS parameter group):

```ini
[mysqld]
max_connections = 200
wait_timeout = 600
interactive_timeout = 600
```

Aplicar cambios (puede requerir reinicio de MySQL).

### Validacion de Exito

En logs de aplicacion, buscar:
```
Connection pool inicializado: 20 conexiones a host:port/database
```

Ejecutar test:
```bash
.venv/bin/python test_load_performance.py
```

Metricas esperadas:
- Throughput > 100 req/s
- Sin errores de "Too many connections"
- Conexiones activas en MySQL < 30

### Rollback

Modificar en codigo:
```python
conn.connect(pool_size=20, use_pooling=False)
```

Reiniciar aplicacion.

---

## Fase 3: Gunicorn Multi-Worker

### Objetivo

Paralelizar procesamiento usando multiples workers de Gunicorn.

### Archivos Nuevos/Modificados

- `gunicorn.conf.py` - Configuracion de Gunicorn (NUEVO)
- `api/server.py` - Singletons globales para compartir datos (MODIFICADO)
- `scripts/start_production.sh` - Script de inicio (NUEVO)

### Deployment

Pasos:

1. Actualizar codigo en servidor de aplicacion

2. Instalar Gunicorn (si no esta instalado):
   ```bash
   .venv/bin/pip install gunicorn uvicorn[standard]
   ```

3. Detener servidor actual (si esta corriendo):
   ```bash
   # Si usa systemd
   sudo systemctl stop recommendation-service

   # O manualmente
   pkill -f "uvicorn"
   ```

4. Iniciar con Gunicorn:
   ```bash
   cd /path/to/RecommendationService
   ./scripts/start_production.sh
   ```

   O con systemd (ver seccion "Deployment con Systemd")

### Configuracion de Workers

Por default: `CPU cores * 2`

Para servidor con 4 vCPU: 8 workers

Ajustar si es necesario:
```bash
GUNICORN_WORKERS=8 ./scripts/start_production.sh
```

### Validacion de Exito

En logs, buscar:
```
Iniciando Gunicorn con 8 workers
Preload app: True
DataService inicializado: <N> users, <M> videos, <K> interactions
RecommendationEngine inicializado
```

Ejecutar test:
```bash
.venv/bin/python test_load_performance.py
```

Metricas esperadas:
- Throughput > 200 req/s
- CPU < 80%
- RAM < 6GB
- Sin memory leaks

### Rollback

Detener Gunicorn:
```bash
pkill -f "gunicorn"
```

Iniciar con Uvicorn (modo anterior):
```bash
.venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 5005
```

---

## Deployment con Systemd (Recomendado)

Crear archivo: `/etc/systemd/system/recommendation-service.service`

```ini
[Unit]
Description=Recommendation Service with Gunicorn
After=network.target mysql.service

[Service]
Type=notify
User=ubuntu
Group=ubuntu
WorkingDirectory=/path/to/RecommendationService
Environment="PATH=/path/to/RecommendationService/.venv/bin"
ExecStart=/path/to/RecommendationService/.venv/bin/gunicorn \
    -c /path/to/RecommendationService/gunicorn.conf.py \
    api.server:app
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=30
PrivateTmp=true
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Habilitar y arrancar:
```bash
sudo systemctl daemon-reload
sudo systemctl enable recommendation-service
sudo systemctl start recommendation-service
sudo systemctl status recommendation-service
```

Ver logs:
```bash
sudo journalctl -u recommendation-service -f
```

---

## Tests Progresivos

### Test 1: Funcionalidad Basica

Despues de cada fase, validar que API responde:

```bash
curl -X POST http://localhost:5005/api/search/total \
  -H "Content-Type: application/json" \
  -d '{
    "SELF_ID": 123,
    "N_VIDEOS": 24,
    "EXCLUDED_IDS": []
  }'
```

Validar:
- Respuesta 200 OK
- JSON valido
- Feed con 24 videos
- Sin errores en logs

### Test 2: Performance Automatizado

```bash
.venv/bin/python test_load_performance.py
```

Validar metricas por fase:
- Fase 1: Throughput > 50 req/s
- Fase 2: Throughput > 100 req/s
- Fase 3: Throughput > 200 req/s

### Test 3: Carga Sostenida

Con Apache Bench (instalar si es necesario):

```bash
# Test con 100 usuarios concurrentes, 1000 requests
ab -n 1000 -c 100 -p payload.json -T application/json \
   http://localhost:5005/api/search/total
```

Crear payload.json:
```json
{
  "SELF_ID": 123,
  "N_VIDEOS": 24,
  "EXCLUDED_IDS": []
}
```

Validar:
- Sin errores (non-2xx responses = 0)
- Latencia promedio < 500ms
- Latencia P95 < 1000ms

### Test 4: Monitoreo de Recursos

Durante test de carga, monitorear:

```bash
# CPU y RAM
htop

# Conexiones MySQL
mysql -e "SHOW PROCESSLIST;"

# Numero de conexiones activas
mysql -e "SHOW STATUS LIKE 'Threads_connected';"
```

Validar:
- CPU < 80%
- RAM < 6GB
- Conexiones MySQL < 50

---

## Monitoreo Post-Deployment

### Metricas Clave

Monitorear durante primeras 24-48 horas:

1. Throughput (requests/segundo)
2. Latencia (P50, P95, P99)
3. Error rate (%)
4. CPU usage (%)
5. RAM usage (GB)
6. Conexiones MySQL activas
7. Slow queries (> 1 segundo)

### Comandos Utiles

Ver slow queries:
```sql
SELECT
    query_time,
    sql_text
FROM mysql.slow_log
WHERE start_time > DATE_SUB(NOW(), INTERVAL 1 HOUR)
ORDER BY query_time DESC
LIMIT 10;
```

Ver uso de indices:
```sql
SELECT
    object_name,
    index_name,
    count_star as uses
FROM performance_schema.table_io_waits_summary_by_index_usage
WHERE object_schema = 'interacpedia'
AND index_name LIKE 'idx_%'
ORDER BY count_star DESC;
```

Ver conexiones activas:
```sql
SHOW PROCESSLIST;
```

### Alertas Recomendadas

Configurar alertas para:
- Throughput < 100 req/s (degradacion)
- Latencia P95 > 2 segundos
- Error rate > 1%
- CPU > 90% por > 5 minutos
- RAM > 7GB
- Conexiones MySQL > 150

---

## Troubleshooting

### Problema: Throughput no mejora despues de Fase 1

Posibles causas:
- Indices no se crearon correctamente
- MySQL no usa los indices
- Estadisticas desactualizadas

Solucion:
1. Verificar indices: `migrations/phase1_validate.sql`
2. Ver plan de ejecucion: `EXPLAIN <query>`
3. Actualizar estadisticas: `ANALYZE TABLE <tabla>`

### Problema: "Too many connections" en MySQL

Posibles causas:
- max_connections muy bajo
- Connection pool no devuelve conexiones
- Conexiones colgadas

Solucion:
1. Aumentar max_connections en MySQL
2. Verificar logs: "Conexion devuelta al pool"
3. Reiniciar aplicacion

### Problema: Workers de Gunicorn crashean

Posibles causas:
- Memoria insuficiente
- Memory leaks
- Timeout muy corto

Solucion:
1. Reducir numero de workers
2. Aumentar RAM del servidor
3. Aumentar timeout en gunicorn.conf.py

### Problema: Performance degrada con tiempo

Posibles causas:
- Memory leaks
- Connection pool se llena
- Datos obsoletos en DataService

Solucion:
1. Monitorear RAM con tiempo
2. Reiniciar workers periodicamente (max_requests)
3. Implementar refresh de datos periodico

---

## Rollback General

Si es necesario revertir TODOS los cambios:

1. Fase 3 (Gunicorn):
   ```bash
   sudo systemctl stop recommendation-service
   # Iniciar con Uvicorn antiguo
   ```

2. Fase 2 (Connection Pooling):
   ```python
   # En codigo: use_pooling=False
   ```

3. Fase 1 (Indices):
   ```bash
   mysql < migrations/phase1_rollback.sql
   ```

Tiempo de rollback completo: 15-30 minutos

---

## Checklist de Deployment

### Pre-Deployment
- [ ] Backup de BD < 24 horas
- [ ] Espacio en disco suficiente
- [ ] Accesos verificados
- [ ] Equipo notificado
- [ ] Ventana de mantenimiento definida

### Fase 1
- [ ] Scripts SQL ejecutados
- [ ] Indices validados
- [ ] Performance mejorada
- [ ] Test automatizado pasado

### Fase 2
- [ ] Codigo actualizado
- [ ] MySQL max_connections configurado
- [ ] Connection pool inicializado
- [ ] Sin errores de conexion

### Fase 3
- [ ] Gunicorn instalado
- [ ] Systemd configurado
- [ ] Workers iniciados correctamente
- [ ] Test de carga pasado

### Post-Deployment
- [ ] Monitoreo configurado
- [ ] Alertas activas
- [ ] Logs verificados
- [ ] Documentacion actualizada

---

## Contactos y Escalamiento

### Durante Deployment

Problemas criticos:
1. Ejecutar rollback de fase correspondiente
2. Notificar a equipo DevOps
3. Documentar problema

### Post-Deployment

Monitoreo continuo por 48 horas.

Si degradacion > 50%: Considerar rollback

Si exito: Proceder con optimizaciones adicionales (Redis, etc.)

---

## Proximos Pasos (Futuro)

Una vez estable el sistema con Fases 1-3:

1. Implementar Redis para cache L1 y L2
   - Mejora esperada: +200-300%
   - Throughput objetivo: > 1000 req/s

2. Implementar read replicas en MySQL
   - Separar reads de writes
   - Mejora esperada: +50-100%

3. Implementar CDN para contenido estatico
   - Reducir latencia global
   - Mejora en experiencia de usuario

4. Auto-scaling con Kubernetes
   - Escalar horizontalmente segun carga
   - Alta disponibilidad

---

## Referencias

- Fase 1: [docs/database/phase1_deployment_guide.md](database/phase1_deployment_guide.md)
- Fase 1 Tecnica: [docs/database/phase1_indexes_technical.md](database/phase1_indexes_technical.md)
- Scripts SQL: `/migrations/phase1_*.sql`
- Configuracion Gunicorn: `/gunicorn.conf.py`
- Script de inicio: `/scripts/start_production.sh`
