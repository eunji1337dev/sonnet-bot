FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="/app"

WORKDIR /app

# Install system dependencies required for ChromaDB (SQLite-VSS compilation etc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsqlite3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Fix Pydantic v1 / Python 3.14+ compatibility issue: 
# We explicitly use python:3.12-slim so ChromaDB works out of the box with Pydantic.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root
RUN addgroup --system appgroup && adduser --system --group appuser
USER appuser

# Healthcheck for UptimeRobot via FastAPI
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/health || exit 1

# Uvicorn will dynamically bind to $PORT as configured in main.py
CMD ["python3", "main.py"]
