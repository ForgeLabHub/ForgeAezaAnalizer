FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core.py .
COPY main.py .
COPY backend/app ./backend/app
COPY backend/scripts ./backend/scripts
COPY db/schema.sql ./backend/auth_schema.sql
# Official organiser dataset: seeded at startup through the app's importer.
COPY dataset/data.json ./dataset/data.json
# Local documentation corpus for the AI Analyst's RAG retrieval.
COPY docs ./docs

# The AI Analyst grounds its answers in docs/ via a prebuilt RAG index
# (AEZA_AI_DOCS_PATH / AEZA_AI_RAG_INDEX_PATH). Ship the docs and build the
# index here: without them the retriever silently returns nothing and answers
# lose their grounding.
RUN mkdir -p /app/backend/data \
    && python -m backend.app.ai.rag --docs /app/docs --out /app/backend/data/rag_index.json

# Run as an unprivileged user; auth storage is mounted under /app/db.
RUN useradd --create-home --uid 10001 aeza \
    && mkdir -p /app/data /app/db \
    && chown -R aeza:aeza /app
USER aeza

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
