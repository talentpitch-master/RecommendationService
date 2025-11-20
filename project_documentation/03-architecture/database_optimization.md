# Fase 1: Indices MySQL - Resultados Validados

## Resumen

**Indices Creados**: 3 indices en tabla resumes

**Mejoras Medidas**:
- videos_query: 182ms -> 143ms (mejora: -39ms, -21%)
- Tiempo de carga: 4.41s -> 4.06s (mejora: -8%)
- Throughput: 19.81 -> 20.20 req/s (mejora: +2%)

**Tiempo de Creacion**: ~5 segundos

---

## Indices

### resumes
1. idx_resumes_search: (deleted_at, status, created_at)
2. idx_resumes_video: (video(255), deleted_at)
3. idx_resumes_user: (user_id, deleted_at)

---

## Deployment

### Crear indices:
```bash
mysql < migrations/create_indexes.sql
```

### Analizar performance:
```bash
mysql < migrations/performance_queries.sql
```

---

## Resultados Detallados

### Baseline (sin indices)
- videos_query: 182ms
- Tiempo de carga: 4.41s
- Throughput: 19.81 req/s

### Con 3 indices
- videos_query: 143ms (-21%)
- Tiempo de carga: 4.06s (-8%)
- Throughput: 20.20 req/s (+2%)

### Conclusion
Los 3 indices en resumes mejoran significativamente la carga de videos, que es el componente principal del sistema.

---

## Optimizaciones de Filtros (Nov 2025)

### Cambios Implementados

**1. Ampliacion de Rango Temporal**
- Anterior: 90 dias
- Actual: 360 dias
- Razon: Ampliar pool de videos disponibles

**2. Eliminacion de Filtro de Engagement**
- Filtro eliminado:
  ```sql
  AND (
      r.views >= 5
      OR tf.avg_rating >= 3.0
      OR matches.match_count >= 1
      OR exhibited.exhibited_count >= 1
  )
  ```
- Razon: Resolver cold start problem para videos nuevos

### Impacto Medido

**Videos Disponibles:**
- Anterior (90 dias + engagement): 689 videos
- Actual (360 dias sin engagement): 2,152 videos
- Ganancia: +1,463 videos (+212.3%)

**Metricas del Sistema:**
- Users: 8,618
- Videos: 2,152
- Interactions: 30,145
- Connections: 887
- Flows: 130

**Caracteristicas de Videos:**
- Videos unicos: 2,152
- Usuarios con videos: 1,188
- Videos con rating: 511
- Total de views: 202,108
- Promedio de views: 93.92

### Racional Tecnico

**Cold Start Problem:**
El filtro de engagement previo impedia que videos nuevos aparecieran en recomendaciones hasta obtener engagement inicial, creando un problema circular: no pueden obtener engagement si no aparecen en recomendaciones.

**Solucion:**
El algoritmo LinUCB (Contextual Bandits) ya maneja naturalmente la exploracion vs explotacion, balanceando automaticamente entre:
- Explotacion: Mostrar videos con buen desempeno historico
- Exploracion: Probar videos nuevos o con poco historial

Por lo tanto, el filtro de engagement era redundante y contraproducente.

### Filtros Actuales

Filtros que permanecen activos:
- status = 'send' (solo videos completados)
- deleted_at IS NULL (resumes y usuarios no borrados)
- created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY) (ultimo ano)
- Exclusion de prueba/test en video y descripcion
- Lista negra de videos aplicada

---

## Proximos Pasos

Para mantener el sistema actualizado:

1. Monitorear metricas de engagement de videos nuevos
2. Validar que el algoritmo LinUCB balancea correctamente exploracion/explotacion
3. Considerar ajustar parametros de exploracion si videos nuevos no obtienen suficiente exposicion
4. Revisar periodicamente la lista negra de videos
