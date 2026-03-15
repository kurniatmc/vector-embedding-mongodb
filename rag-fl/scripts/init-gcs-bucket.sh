#!/bin/bash
# Create GCS bucket on startup (for fake-gcs-server)

echo "Waiting for fake-gcs-server to be ready..."
until curl -sf http://localhost:4443/storage/v1/b >/dev/null 2>&1; do
  sleep 1
done

echo "Creating bucket: rag-fl-documents..."
curl -s -X POST "http://localhost:4443/storage/v1/b" \
  -H "Content-Type: application/json" \
  -d '{"name": "rag-fl-documents"}'

echo "Bucket initialization complete!"
