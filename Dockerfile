FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements*.txt /app/backend/

RUN pip install --upgrade pip \
    && pip install -r /app/backend/requirements.txt -r /app/backend/requirements-youtube.txt

COPY backend /app/backend
COPY frontend /app/frontend
COPY docs /app/docs
COPY scripts /app/scripts
COPY README.md /app/README.md
COPY .env.example /app/.env.example

RUN mkdir -p /app/data \
    /app/media \
    /app/models \
    /app/secrets

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --no-create-home app \
    && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
