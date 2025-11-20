-- ============================================================================
-- FASE 1: ANALISIS DE PERFORMANCE POST-INDICES
-- ============================================================================
--
-- Proposito: Medir mejora de performance despues de crear indices
--
-- Como usar:
--   1. Ejecutar queries individuales
--   2. Medir tiempo de cada query (usar \timing en psql o equivalente)
--   3. Comparar con tiempos baseline:
--      - users_query: Baseline 308ms, Target <100ms
--      - videos_query: Baseline 180ms, Target <80ms
--      - views_query: Baseline 207ms, Target <70ms
--      - interactions_query: Baseline 158ms, Target <50ms
--
-- IMPORTANTE:
--   - Ejecutar en ambiente similar a produccion
--   - Ejecutar multiples veces y promediar
--   - Limpiar cache entre ejecuciones si es posible
--   - Monitorear uso de CPU/memoria durante ejecucion
--
-- ============================================================================

USE interacpedia;

-- ============================================================================
-- TEST 1: USERS QUERY
-- ============================================================================
-- Baseline: 308ms
-- Target: <100ms
-- Impacto esperado: -74%
-- ============================================================================

EXPLAIN
SELECT
    u.id,
    u.name,
    u.email,
    COALESCE(NULLIF(TRIM(u.city), ''), 'Unknown') as city,
    COALESCE(NULLIF(TRIM(u.country), ''), 'Unknown') as country,
    u.created_at,
    p.skills,
    p.languages,
    p.tools,
    p.knowledge,
    p.hobbies,
    p.type_talentees,
    p.opencall_objective
FROM users u
LEFT JOIN profiles p ON u.id = p.user_id
WHERE u.deleted_at IS NULL
AND (u.created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY)
     OR u.updated_at >= DATE_SUB(NOW(), INTERVAL 360 DAY));

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indices: idx_users_active, idx_users_updated

-- ============================================================================
-- TEST 2: VIDEOS QUERY (Simplificada)
-- ============================================================================
-- Baseline: 180ms
-- Target: <80ms
-- Impacto esperado: -67%
-- ============================================================================

EXPLAIN
SELECT
    r.id,
    r.user_id,
    r.video,
    r.views,
    r.created_at
FROM resumes r
STRAIGHT_JOIN users u ON r.user_id = u.id
WHERE r.deleted_at IS NULL
AND r.status = 'send'
AND r.video IS NOT NULL
AND u.deleted_at IS NULL
AND r.created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indices: idx_resumes_search, idx_resumes_user

-- ============================================================================
-- TEST 3: VIEWS QUERY (Activity Log)
-- ============================================================================
-- Baseline: 207ms
-- Target: <70ms
-- Impacto esperado: -66%
-- ============================================================================

EXPLAIN
SELECT
    causer_id as user_id,
    subject_id as video_id,
    created_at
FROM activity_log
WHERE description LIKE '%video%view%'
AND causer_id IS NOT NULL
AND subject_id IS NOT NULL
AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_activity_views o idx_activity_dates

-- ============================================================================
-- TEST 4: INTERACTIONS QUERY - Team Feedbacks
-- ============================================================================
-- Baseline (parte de 158ms total)
-- Target: <50ms
-- Impacto esperado: -68%
-- ============================================================================

EXPLAIN
SELECT
    user_id,
    model_id as video_id,
    CASE WHEN value > 5 THEN 5 ELSE value END as rating,
    created_at,
    'rating' as interaction_type
FROM team_feedbacks
WHERE type = 'ranking_resume'
AND value > 0
AND user_id IS NOT NULL
AND created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_feedbacks_rankings

-- ============================================================================
-- TEST 5: INTERACTIONS QUERY - Likes
-- ============================================================================

EXPLAIN
SELECT
    user_id,
    model_id as video_id,
    3.0 as rating,
    created_at,
    'save' as interaction_type
FROM likes
WHERE type = 'save'
AND user_id IS NOT NULL
AND created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_likes_user

-- ============================================================================
-- TEST 6: INTERACTIONS QUERY - Matches
-- ============================================================================

EXPLAIN
SELECT
    user_id,
    model_id as video_id,
    4.0 as rating,
    created_at,
    'match' as interaction_type
FROM matches
WHERE status = 'accepted'
AND user_id IS NOT NULL
AND created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_matches_user

-- ============================================================================
-- TEST 7: AGREGACIONES - Team Feedbacks por Model
-- ============================================================================
-- Usado en videos_query para calcular avg_rating

EXPLAIN
SELECT
    model_id,
    AVG(value) as avg_rating,
    COUNT(*) as rating_count
FROM team_feedbacks
WHERE type = 'ranking_resume'
AND value > 0
GROUP BY model_id;

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_feedbacks_model

-- ============================================================================
-- TEST 8: AGREGACIONES - Matches por Model
-- ============================================================================
-- Usado en videos_query para calcular match_count

EXPLAIN
SELECT
    model_id,
    COUNT(*) as match_count
FROM matches
WHERE status = 'accepted'
GROUP BY model_id;

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_matches_accepted

-- ============================================================================
-- TEST 9: FLOWS QUERY
-- ============================================================================

EXPLAIN
SELECT
    c.id,
    c.user_id,
    c.video,
    c.name,
    c.description,
    c.created_at
FROM challenges c
JOIN users u ON c.user_id = u.id
WHERE c.deleted_at IS NULL
AND c.status = 'published'
AND c.video IS NOT NULL
AND (c.created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY)
     OR c.updated_at >= DATE_SUB(NOW(), INTERVAL 360 DAY));

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_challenges_published

-- ============================================================================
-- TEST 10: USER CONNECTIONS
-- ============================================================================

EXPLAIN
SELECT
    from_id as user_id,
    to_id as connected_user_id,
    status,
    created_at
FROM user_connections
WHERE status = 'accepted'
AND created_at >= DATE_SUB(NOW(), INTERVAL 360 DAY);

-- Ejecutar query real (sin EXPLAIN) y medir tiempo
-- Debe usar indice: idx_connections_accepted

-- ============================================================================
-- ANALISIS DE EXPLAIN PLANS
-- ============================================================================

-- Que buscar en los EXPLAIN:
--
-- 1. "type" column debe ser:
--    - "ref" o "range" (BUENO - usa indices)
--    - "ALL" (MALO - full table scan, indice no se usa)
--
-- 2. "key" column debe mostrar:
--    - Nombre del indice que se esta usando
--    - NULL = indice no se usa (MALO)
--
-- 3. "rows" column:
--    - Numero menor de rows = indice mas selectivo (BUENO)
--    - Numero alto de rows = indice poco util o no usado
--
-- 4. "Extra" column:
--    - "Using index" = query solo usa indice (EXCELENTE)
--    - "Using where; Using index" = usa indice y filtra (BUENO)
--    - "Using filesort" = ordenamiento sin indice (MALO)
--    - "Using temporary" = tabla temporal (MALO)
--
-- ============================================================================
-- COMPARACION DE TIEMPOS
-- ============================================================================

-- Completar esta tabla manualmente con los tiempos medidos:

-- | Query                  | Baseline | Post-Indices | Mejora | Target | Status |
-- |------------------------|----------|--------------|--------|--------|--------|
-- | users_query            | 308ms    | _____ms      | ____%  | <100ms | ___    |
-- | videos_query           | 180ms    | _____ms      | ____%  | <80ms  | ___    |
-- | views_query            | 207ms    | _____ms      | ____%  | <70ms  | ___    |
-- | interactions_query     | 158ms    | _____ms      | ____%  | <50ms  | ___    |
-- | feedbacks_aggregation  | N/A      | _____ms      | N/A    | <30ms  | ___    |
-- | matches_aggregation    | N/A      | _____ms      | N/A    | <20ms  | ___    |
-- | flows_query            | N/A      | _____ms      | N/A    | <50ms  | ___    |
-- | connections_query      | N/A      | _____ms      | N/A    | <30ms  | ___    |

-- ============================================================================
-- PROXIMO PASO
-- ============================================================================
--
-- Si todas las queries cumplen targets:
--   - Ejecutar: python test_load_performance.py
--   - Validar throughput > 50 req/s
--   - Proceder a Fase 2 (Connection Pooling)
--
-- Si algunas queries NO cumplen targets:
--   - Revisar EXPLAIN plans
--   - Verificar que indices existen (SHOW INDEX FROM <table>)
--   - Ejecutar ANALYZE TABLE <table> para actualizar estadisticas
--   - Considerar ajustar indices o agregar indices adicionales
--
-- ============================================================================
