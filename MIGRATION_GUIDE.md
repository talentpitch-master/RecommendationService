# Guía de Migración: Simplificación de Variables de Entorno

## Resumen

Se ha simplificado el sistema de configuración eliminando los prefijos `STG_` y `PROD_` y la variable `ENVIRONMENT`. Ahora las variables son directas y simples.

## ¿Qué cambió?

### Antes (❌)

```ini
ENVIRONMENT=staging

STG_MYSQL_HOST=staging-host.example.com
STG_MYSQL_USER=staging_user
STG_MYSQL_PASSWORD=staging_pass
STG_MYSQL_DB=staging_db
STG_MYSQL_PORT=3306

PROD_MYSQL_HOST=prod-host.example.com
PROD_MYSQL_USER=prod_user
PROD_MYSQL_PASSWORD=prod_pass
PROD_MYSQL_DB=prod_db
PROD_MYSQL_PORT=3306
```

**Problemas:**
- Variables duplicadas con prefijos
- Lógica de concatenación complicada en el código
- Dificulta el cambio de ambiente
- Mayor posibilidad de errores

### Ahora (✅ Buena práctica)

```ini
MYSQL_HOST=mysql-host.example.com
MYSQL_PORT=3306
MYSQL_USER=mysql_user
MYSQL_PASSWORD=mysql_pass
MYSQL_DB=mysql_db
```

**Beneficios:**
- Variables directas sin concatenación
- Más simple de entender y mantener
- Fácil cambio de ambiente (solo editar valores)
- Menos propenso a errores

## Cómo migrar

### Para usuarios actuales

Si tienes un archivo `credentials/.env` existente:

1. **Elimina las variables con prefijos STG_ y PROD_**
2. **Elimina la variable ENVIRONMENT**
3. **Agrega las variables directas con los valores que necesites**

**Ejemplo:**

Si estabas usando `ENVIRONMENT=staging` con estas variables:
```ini
STG_MYSQL_HOST=staging.db.example.com
STG_MYSQL_USER=user_staging
STG_MYSQL_PASSWORD=pass_staging
STG_MYSQL_DB=staging_db
```

Simplemente reemplázalas con:
```ini
MYSQL_HOST=staging.db.example.com
MYSQL_USER=user_staging
MYSQL_PASSWORD=pass_staging
MYSQL_DB=staging_db
```

### Cambio de ambiente

Para cambiar entre staging y production, simplemente edita los valores en `credentials/.env`:

**Para staging:**
```ini
MYSQL_HOST=staging-mysql.example.com
MYSQL_USER=staging_user
MYSQL_PASSWORD=staging_pass
MYSQL_DB=staging_db
```

**Para production:**
```ini
MYSQL_HOST=prod-mysql.example.com
MYSQL_USER=prod_user
MYSQL_PASSWORD=prod_pass
MYSQL_DB=prod_db
```

No necesitas:
- ❌ Cambiar `ENVIRONMENT`
- ❌ Duplicar variables con prefijos
- ❌ Reconstruir Docker para cambiar ambiente

## Variables actualizadas

### Variables eliminadas
- `ENVIRONMENT`
- `STG_MYSQL_*`
- `PROD_MYSQL_*`

### Variables ahora usadas (directas)
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_DB`

### Variables que no cambiaron
- `SSH_HOST`
- `SSH_USER`
- `REDIS_HOST`
- `REDIS_PASSWORD`
- `REDIS_PORT`
- `REDIS_SCHEME`
- `API_HOST`
- `API_PORT`
- `FLUSH_INTERVAL_SECONDS`
- `FLUSH_THRESHOLD_ACTIVITIES`

## Archivos modificados

### Código
- `core/database.py` - Eliminada lógica de prefijos
- `example.env` - Actualizado con variables simples

### Documentación
- `README.md` - Actualizado con nuevas variables
- `docs/project-summary.md` - Actualizado con ejemplos
- `docs/architecture.md` - Actualizado con ejemplos de código
- `docs/development-guide.md` - Eliminadas referencias a ENVIRONMENT

## Docker

Ya no necesitas pasar la variable `ENVIRONMENT` al contenedor Docker:

**Antes:**
```bash
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -e ENVIRONMENT=production \  # ❌ Ya no es necesario
  talentpitch-search:latest
```

**Ahora:**
```bash
docker run -d --name source \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  talentpitch-search:latest
```

## ¿Preguntas?

Si tienes problemas con la migración, verifica que:
1. Todas las variables tienen valores
2. No hay variables con prefijos STG_ o PROD_ en tu `.env`
3. No existe la variable `ENVIRONMENT` en tu `.env`
4. Las credenciales corresponden al ambiente que quieres usar

