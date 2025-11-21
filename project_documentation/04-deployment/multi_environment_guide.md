# Guía de Despliegue Multi-Entorno

**Última actualización:** Noviembre 2025
**Versión:** 1.0

Esta guía documenta cómo desplegar el Recommendation Service en los tres entornos soportados: Local, Docker y GitHub.

---

## Tabla de Contenidos

1. [Requisitos Previos](#requisitos-previos)
2. [Entorno Local](#entorno-local)
3. [Entorno Docker](#entorno-docker)
4. [Entorno GitHub](#entorno-github)
5. [Validación de Despliegue](#validación-de-despliegue)
6. [Troubleshooting](#troubleshooting)

---

## Requisitos Previos

### Para TODOS los entornos:
- Python 3.13+
- Git configurado

### Para entorno Local:
- Virtualenv o venv
- Acceso a credenciales SSH (credentials/.env y .cer)

### Para entorno Docker:
- Docker Desktop o Docker Engine 20.10+
- Docker Compose v2+
- 2GB RAM disponible mínimo

### Para entorno GitHub:
- Repositorio en GitHub
- Acceso a GitHub Actions (habilitado por defecto)
- Secrets configurados (para deploy a EKS, opcional)

---

## Entorno Local

**Propósito:** Desarrollo y debugging
**Startup time:** ~5 segundos
**Ideal para:** Desarrollo rápido, debugging con breakpoints

### Setup Inicial

```bash
# 1. Crear virtual environment
python3.13 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 2. Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3. Verificar credenciales
ls credentials/
# Debe mostrar: .env y talethpitch-develop-bastion.cer
```

### Ejecutar Servicio

```bash
# Modo desarrollo (Uvicorn con hot-reload)
python main.py

# Modo producción local (Gunicorn)
bash scripts/start_production.sh
```

### Verificar

```bash
# Health check
curl http://localhost:5002/health

# Endpoint de búsqueda
curl http://localhost:5002/search?user_id=1234

# Ver logs en tiempo real
tail -f logs/api.log
```

### Detener

```bash
# Ctrl+C en la terminal donde corre el servicio

# O encontrar y matar el proceso:
lsof -ti:5002 | xargs kill -9
```

---

## Entorno Docker

**Propósito:** Validación pre-despliegue, consistencia de entorno
**Startup time:** ~60 segundos (build) + 10 segundos (start)
**Ideal para:** Validar que el código funciona en producción

### Opción A: Docker Compose (Recomendado)

```bash
# Build y start en un solo comando
docker compose up --build

# Build sin cache (si hubo cambios en dependencias)
docker compose build --no-cache
docker compose up

# Modo detached (background)
docker compose up -d

# Ver logs
docker compose logs -f

# Detener
docker compose down
```

### Opción B: Docker Standalone

```bash
# Build imagen
docker build -t recommendation-service:latest .

# Run container
docker run -d \
  --name recommendation-api \
  -p 5002:5002 \
  -v $(pwd)/credentials:/app/credentials:ro \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data:/app/data:ro \
  recommendation-service:latest

# Ver logs
docker logs -f recommendation-api

# Detener y remover
docker stop recommendation-api
docker rm recommendation-api
```

### Verificar Container

```bash
# Health check
curl http://localhost:5002/health

# Inspeccionar container
docker inspect recommendation-api

# Ver recursos usados
docker stats recommendation-api

# Ejecutar comando dentro del container
docker exec -it recommendation-api sh
```

### Troubleshooting Docker

**Problema:** Build falla en instalación de scipy/pandas
```bash
# Solución: Limpiar cache y rebuilder
docker builder prune -a
docker compose build --no-cache
```

**Problema:** Container inicia pero no responde
```bash
# Ver logs detallados
docker compose logs -f

# Verificar que el túnel SSH funciona
docker exec -it talentpitch-search-api sh
# Dentro del container:
netstat -tlnp | grep 3307
```

**Problema:** Puerto 5002 ya en uso
```bash
# Encontrar proceso usando el puerto
lsof -ti:5002

# Matar el proceso
lsof -ti:5002 | xargs kill -9

# O cambiar puerto en docker-compose.yml:
# ports:
#   - "5003:5002"
```

---

## Entorno GitHub

**Propósito:** CI/CD, validación automática, despliegue a producción
**Startup time:** Variable (GitHub Actions queue)
**Ideal para:** Validar PRs, desplegar a EKS

### Workflows Disponibles

El proyecto tiene 3 workflows configurados:

#### 1. Pull Request Validation (`pull_request.yml`)

**Trigger:** Automático en cada PR a `main` o `develop`
**Propósito:** Validar que el código se puede desplegar sin problemas

**Jobs:**
- ✅ Docker Build Validation: Construye imagen Docker (no hace push)
- ✅ Python Syntax & Dependencies: Valida sintaxis y estructura
- ✅ Summary: Resumen de validación

**Uso:**
```bash
# 1. Crear branch feature
git checkout -b feature/nueva-funcionalidad

# 2. Hacer cambios
git add .
git commit -m "feat: Nueva funcionalidad"

# 3. Push a GitHub
git push origin feature/nueva-funcionalidad

# 4. Crear Pull Request en GitHub
# El workflow se ejecuta automáticamente

# 5. Ver resultados en GitHub Actions tab
# ✅ = Listo para merge
# ❌ = Hay problemas, revisar logs
```

**Qué valida:**
- ✓ Dockerfile se puede construir sin errores
- ✓ Todas las dependencias de requirements.txt son válidas
- ✓ Sintaxis Python es correcta
- ✓ Archivos críticos existen (api/server.py, core/database.py, etc.)

#### 2. Deploy to Development (`develop.yml`)

**Trigger:** Push a branch `develop`
**Propósito:** Desplegar automáticamente a EKS development

**Jobs:**
- Build: Construye imagen y la sube a Amazon ECR
- Deploy: Despliega a Kubernetes cluster development

**Uso:**
```bash
# 1. Hacer merge de PR a develop
# (Se ejecuta automáticamente)

# 2. Ver logs en GitHub Actions
# - Build tarda ~2-3 minutos
# - Deploy tarda ~1-2 minutos

# 3. Verificar deployment
kubectl get pods -n development
kubectl logs -n development deployment/recommendation-service
```

**Requiere Secrets (ya configurados):**
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `REGION`
- `ECR_REPOSITORY`

#### 3. Create ECR Repository (`ecr.yaml`)

**Trigger:** Manual (workflow_dispatch)
**Propósito:** Crear repositorio ECR si no existe

**Uso:**
```bash
# En GitHub:
# Actions → Create ECR Repository → Run workflow
```

### Configurar Branch Protection

**Recomendado para evitar código roto en develop/main:**

1. Ir a GitHub → Settings → Branches
2. Add rule para `develop`:
   - ✅ Require pull request before merging
   - ✅ Require status checks to pass before merging
     - Seleccionar: `validate-docker-build`, `validate-python-syntax`
   - ✅ Require branches to be up to date before merging
3. Repetir para `main`

**Resultado:** No se puede hacer merge si las validaciones fallan.

### GitHub Actions Tips

**Ver logs detallados:**
```
GitHub → Actions → [Workflow run] → [Job] → [Step]
```

**Re-ejecutar workflow fallido:**
```
GitHub → Actions → [Workflow run] → Re-run jobs
```

**Ejecutar workflow manualmente:**
```
GitHub → Actions → [Workflow name] → Run workflow
```

**Descargar logs:**
```
GitHub → Actions → [Workflow run] → ⋯ → Download log archive
```

---

## Validación de Despliegue

### Checklist General (Aplicable a TODOS los entornos)

Después de desplegar, validar:

```bash
# 1. Health check responde
curl http://localhost:5002/health
# Esperado: {"status": "healthy"}

# 2. Endpoint de búsqueda funciona
curl "http://localhost:5002/search?user_id=1234"
# Esperado: JSON con lista de videos

# 3. Logs no tienen errores críticos
# Local: tail -f logs/api.log
# Docker: docker compose logs -f
# GitHub/EKS: kubectl logs -f deployment/recommendation-service

# 4. Métricas básicas
curl http://localhost:5002/metrics  # Si está configurado
```

### Validación por Entorno

#### Local
```bash
✓ Túnel SSH conectado (ver logs)
✓ Connection pool MySQL activo
✓ Puerto 5002 escuchando
✓ Hot-reload funciona (cambiar código y ver recarga)
```

#### Docker
```bash
✓ Container running: docker ps | grep recommendation
✓ Health check pasa: docker inspect --format='{{.State.Health.Status}}' talentpitch-search-api
✓ Logs limpios: docker compose logs | grep ERROR
✓ Volúmenes montados: docker inspect talentpitch-search-api | grep Mounts -A 20
```

#### GitHub
```bash
✓ Workflow completó sin errores (green checkmark)
✓ Docker image se construyó correctamente
✓ Todos los checks pasaron
✓ PR tiene approval y está listo para merge
```

---

## Troubleshooting

### Error: "Credenciales SSH incompletas"

**Entornos:** Local, Docker

**Causa:** Falta archivo credentials/.env o credentials/*.cer

**Solución:**
```bash
# Verificar archivos
ls -la credentials/

# Debe mostrar:
# .env
# talethpitch-develop-bastion.cer

# Si faltan, contactar al equipo para obtenerlos
```

### Error: "Port 5002 already in use"

**Entornos:** Local, Docker

**Solución:**
```bash
# Encontrar y matar proceso
lsof -ti:5002 | xargs kill -9

# O cambiar puerto en configuración
# Local: export API_PORT=5003
# Docker: Editar docker-compose.yml ports
```

### Error: "Connection refused to MySQL"

**Entornos:** Local, Docker, GitHub

**Causa:** Túnel SSH no está activo o credenciales incorrectas

**Solución:**
```bash
# Verificar credenciales en .env
cat credentials/.env | grep MYSQL

# Verificar conectividad SSH
ssh -i credentials/*.cer ${SSH_USER}@${SSH_HOST}

# Ver logs del túnel
# Los logs deben mostrar: "Tunel SSH activo: localhost:3307"
```

### Error: Docker build falla en scipy/pandas

**Entornos:** Docker, GitHub

**Causa:** Cache corrupto o dependencias Alpine faltantes

**Solución:**
```bash
# Limpiar cache Docker
docker builder prune -a

# Rebuild sin cache
docker compose build --no-cache

# Si persiste, verificar Dockerfile tiene:
# RUN apk add --no-cache gcc g++ gfortran openblas-dev lapack-dev
```

### Error: GitHub Actions workflow falla

**Entornos:** GitHub

**Diagnóstico:**
1. Ir a Actions → [Failed workflow] → [Failed job]
2. Ver logs del step que falló
3. Buscar línea con "Error:" o "FAILED"

**Soluciones comunes:**

**Falla en Docker build:**
```bash
# Localmente, reproducir el error:
docker build --platform linux/amd64 -t test .

# Revisar Dockerfile y requirements.txt
```

**Falla en Python syntax:**
```bash
# Localmente, validar sintaxis:
python -m py_compile api/*.py core/*.py services/*.py utils/*.py
```

**Falla en Deploy to EKS:**
```bash
# Verificar secrets en GitHub:
# Settings → Secrets → Actions
# Deben existir: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, REGION, ECR_REPOSITORY
```

### Error: Gunicorn workers no inician

**Entornos:** Docker, GitHub/EKS

**Causa:** Timeout, out of memory, o import error

**Solución:**
```bash
# Ver logs completos
docker compose logs -f | grep gunicorn

# Errores comunes:
# - "ModuleNotFoundError": Falta dependencia en requirements.txt
# - "MemoryError": Aumentar RAM del container
# - "Timeout": Aumentar --timeout en CMD del Dockerfile
```

---

## Comandos Rápidos de Referencia

### Local
```bash
# Start
source .venv/bin/activate && python main.py

# Test
curl http://localhost:5002/health

# Stop
Ctrl+C o lsof -ti:5002 | xargs kill -9
```

### Docker
```bash
# Start
docker compose up -d

# Logs
docker compose logs -f

# Test
curl http://localhost:5002/health

# Stop
docker compose down
```

### GitHub
```bash
# Validar PR
git push origin feature-branch
# → Crear PR en GitHub
# → Esperar checks ✅

# Deploy a develop
git checkout develop
git merge feature-branch
git push origin develop
# → Automático deploy a EKS

# Ver estado
# GitHub → Actions → [Workflow]
```

---

## Mejores Prácticas

1. **Desarrollo Local:**
   - Usar virtual environment siempre
   - Commit frequent, push cuando funciona
   - Validar con Docker antes de PR

2. **Docker:**
   - Usar `docker compose up --build` después de cambiar requirements.txt
   - Limpiar imágenes viejas: `docker image prune -a`
   - Monitorear logs durante deployment

3. **GitHub:**
   - Crear PRs pequeños y enfocados
   - Esperar a que checks pasen antes de pedir review
   - Configurar branch protection en develop/main
   - No hacer push directo a develop/main

4. **Debugging:**
   - Revisar logs primero (90% de problemas están ahí)
   - Reproducir localmente antes de debugging en Docker
   - Usar `docker exec -it` para inspeccionar container

---

## Contacto y Soporte

**Problemas de deployment:**
- Revisar esta guía primero
- Verificar logs del entorno correspondiente
- Contactar al equipo de DevOps

**Cambios en infraestructura:**
- Actualizar esta documentación
- Notificar al equipo antes de cambios en workflows

**Preguntas:**
- Abrir issue en GitHub con etiqueta `deployment`
