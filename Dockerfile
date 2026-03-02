FROM python:3.9-slim-buster

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VERSION=1.4.2 \
    PYTHONPATH="/app"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-asyncio

COPY . .

RUN addgroup --system appgroup && adduser --system --group appuser
USER appuser

CMD ["python3", "main.py"]
