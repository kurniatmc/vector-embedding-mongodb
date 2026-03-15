FROM python:3.11-slim-bookworm

# libmagic1 is required by python-magic for MIME detection
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
# Build context = project root, so paths are relative to rag-fl/
COPY services/ingestion/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared utilities (schemas + utils)
COPY shared/ ./shared/

# Copy ingestion service code
COPY services/ingestion/ ./services/ingestion/

# Create /input and /output directories (bind-mounted at runtime)
RUN mkdir -p /input /output/flat-images /output/embedding-db

EXPOSE 8001

CMD ["uvicorn", "services.ingestion.app.main:app", "--host", "0.0.0.0", "--port", "8001"]
