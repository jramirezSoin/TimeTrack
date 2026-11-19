FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias primero para aprovechar la caché de capas.
COPY dashboard/requirements.txt dashboard/requirements.txt
RUN pip install -r dashboard/requirements.txt

# Código. azure/config.json y data/ quedan fuera (.dockerignore): se montan como volúmenes.
COPY timetrack/ timetrack/
COPY azure/ azure/
COPY siges/ siges/
COPY dashboard/app/ dashboard/app/

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"

# 0.0.0.0 es necesario dentro del contenedor; el acceso se limita a localhost en docker-compose.yml.
CMD ["uvicorn", "dashboard.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
