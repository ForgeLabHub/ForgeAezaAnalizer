FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY core.py main.py ./
COPY backend/__init__.py ./backend/__init__.py
COPY backend/auth ./backend/auth
COPY backend/config.py backend/database.py backend/users.py ./backend/
COPY backend/app ./backend/app
COPY backend/scripts ./backend/scripts
COPY db/schema.sql ./backend/auth_schema.sql
COPY dataset/data.json ./dataset/data.json
COPY dataset/presentation.json ./dataset/presentation.json
COPY docs ./docs

RUN mkdir -p /app/backend/data \
    && python -m backend.app.ai.rag --docs /app/docs --out /app/backend/data/rag_index.json

RUN useradd --create-home --uid 10001 aeza \
    && mkdir -p /app/data /app/db \
    && chown -R aeza:aeza /app
USER aeza

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
