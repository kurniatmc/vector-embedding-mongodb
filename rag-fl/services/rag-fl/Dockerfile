FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY services/rag-fl/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy shared utilities and the service
COPY shared/ ./shared/
COPY services/rag-fl/ ./services/rag-fl/

# PYTHONPATH: project root (for shared.*) + service dir (for classifier, chunker, etc.)
ENV PYTHONPATH=/app/services/rag-fl:/app

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=30s \
  CMD curl -f http://localhost:8004/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
