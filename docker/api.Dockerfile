FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY backend/requirements-dev.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock \
    && groupadd --system sardars \
    && useradd --system --gid sardars --home /app sardars \
    && mkdir -p /app/data/uploads \
    && chown -R sardars:sardars /app/data

COPY backend/ /app/backend/
COPY alembic.ini /app/alembic.ini

USER sardars
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
