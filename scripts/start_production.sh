#!/bin/bash

##############################################################################
# Script de inicio para ambiente de produccion
#
# Uso:
#   ./scripts/start_production.sh
#
# Variables de entorno opcionales:
#   GUNICORN_WORKERS - Numero de workers (default: CPU cores * 2)
#   GUNICORN_PORT - Puerto (default: 5005)
#   GUNICORN_LOG_LEVEL - Log level (default: info)
##############################################################################

set -e  # Exit on error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funciones de logging
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Directorio del proyecto
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

log_info "Directorio del proyecto: $PROJECT_DIR"

# Verificar que existe .venv
if [ ! -d ".venv" ]; then
    log_error "No se encontro .venv. Ejecutar: python3 -m venv .venv"
    exit 1
fi

# Verificar que existe .env
if [ ! -f ".env" ]; then
    log_error "No se encontro archivo .env en raiz del proyecto"
    exit 1
fi

# Verificar que existe gunicorn
if [ ! -f ".venv/bin/gunicorn" ]; then
    log_warn "Gunicorn no encontrado, instalando..."
    .venv/bin/pip install gunicorn uvicorn[standard] -q
fi

# Variables de entorno con defaults
WORKERS=${GUNICORN_WORKERS:-$(python3 -c "import multiprocessing; print(multiprocessing.cpu_count() * 2)")}
PORT=${GUNICORN_PORT:-5005}
LOG_LEVEL=${GUNICORN_LOG_LEVEL:-info}

log_info "Configuracion:"
log_info "  Workers: $WORKERS"
log_info "  Port: $PORT"
log_info "  Log Level: $LOG_LEVEL"

# Verificar que puerto no este en uso
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    log_error "Puerto $PORT ya esta en uso"
    log_info "Procesos usando puerto $PORT:"
    lsof -Pi :$PORT -sTCP:LISTEN
    exit 1
fi

# Crear directorio de logs si no existe
mkdir -p logs

# Backup de logs anterior
if [ -f "logs/gunicorn_access.log" ]; then
    mv logs/gunicorn_access.log logs/gunicorn_access.log.$(date +%Y%m%d_%H%M%S)
fi
if [ -f "logs/gunicorn_error.log" ]; then
    mv logs/gunicorn_error.log logs/gunicorn_error.log.$(date +%Y%m%d_%H%M%S)
fi

log_info "Iniciando servidor de produccion..."
log_info "Logs en: logs/gunicorn_access.log y logs/gunicorn_error.log"
log_info ""
log_info "Para detener: Ctrl+C o kill -TERM <PID>"
log_info ""

# Iniciar Gunicorn
exec .venv/bin/gunicorn \
    -c gunicorn.conf.py \
    --workers $WORKERS \
    --bind 0.0.0.0:$PORT \
    --log-level $LOG_LEVEL \
    --access-logfile logs/gunicorn_access.log \
    --error-logfile logs/gunicorn_error.log \
    api.server:app
