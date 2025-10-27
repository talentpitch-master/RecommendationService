FROM --platform=linux/amd64 python:3.13-alpine3.22

RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    linux-headers \
    libffi-dev \
    openssl-dev \
    git && \
    apk upgrade --no-cache busybox busybox-binsh --repository=http://dl-cdn.alpinelinux.org/alpine/edge/main || true

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir git+https://github.com/pypa/pip.git@main || \
    pip install --no-cache-dir --upgrade pip

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/logs /app/data

ENV PYTHONUNBUFFERED=1

EXPOSE 5002

CMD ["gunicorn", "api.server:app", "--bind", "0.0.0.0:5002", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
