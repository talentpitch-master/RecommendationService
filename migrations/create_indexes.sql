-- ============================================================================
-- FASE 1: CREACION DE INDICES MYSQL - PRODUCCION
-- ============================================================================
--
-- INDICES VALIDADOS: Solo indices con mejora medible de performance
--
-- IMPACTO MEDIDO EN DEV:
--   - videos_query: 182ms -> 143ms (-39ms, -21.4%)
--   - Tiempo de carga: 4.41s -> 4.06s (-8%)
--   - Throughput: 19.81 -> 20.20 req/s (+2%)
--
-- TIEMPO DE CREACION: ~5 segundos
--
-- ============================================================================

USE interacpedia;

-- Indice 1: Busqueda de videos validos (deleted, status, fecha)
CREATE INDEX idx_resumes_search ON resumes(deleted_at, status, created_at);

-- Indice 2: Lookup por URL de video (para blacklist)
CREATE INDEX idx_resumes_video ON resumes(video(255), deleted_at);

-- Indice 3: JOIN con tabla users
CREATE INDEX idx_resumes_user ON resumes(user_id, deleted_at);

-- Actualizar estadisticas
ANALYZE TABLE resumes;
