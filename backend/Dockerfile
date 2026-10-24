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
COPY dataset/data.json ./dataset/data.json

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
