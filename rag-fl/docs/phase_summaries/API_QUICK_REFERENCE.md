# RAG-FL API Quick Reference Card
**Version:** 6.0.0 | **Last Updated:** 2026-03-08

---

## Service Ports

| Service | Port | Base URL |
|---------|------|----------|
| Ingestion | 8001 | http://localhost:8001 |
| RAG-FL Pipeline | 8004 | http://localhost:8004 |
| UI (Next.js) | 3001 | http://localhost:3001 |

---

## Ingestion API (Port 8001)

### Upload Document
```bash
POST /ingest
curl -X POST http://localhost:8001/ingest \
  -F "file=@document.pdf" \
  -F "report_series=monthly_churn" \
  -F "report_period=2025-01"
```

### List Documents
```bash
GET /documents
curl http://localhost:8001/documents
```

### Get Document
```bash
GET /document/{doc_id}
curl http://localhost:8001/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e
```

### Delete Document
```bash
DELETE /document/{doc_id}
curl -X DELETE http://localhost:8001/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e
```

### Health Check
```bash
GET /health
curl http://localhost:8001/health
```

---

## Pipeline API (Port 8004)

### Process Document
```bash
POST /process
curl -X POST http://localhost:8004/process \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"d8703de2-2d5a-4b1b-8113-cfcea25deb5e","classify_only":false}'
```

### Get Document Status
```bash
GET /document/{doc_id}/status
curl http://localhost:8004/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/status
```

### Get All Documents
```bash
GET /documents
curl http://localhost:8004/documents
```

### Get Page Profiles
```bash
GET /document/{doc_id}/pages
curl http://localhost:8004/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/pages
```

### Get Page Chunks
```bash
GET /document/{doc_id}/chunks/{page_number}
curl http://localhost:8004/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/chunks/1
```

### Get Page Image (Multimodal)
```bash
GET /image/{doc_id}/{page_number}
curl http://localhost:8004/image/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/1 -o page1.png
```

### Get Runtime Config
```bash
GET /config
curl http://localhost:8004/config
```

### Health Check
```bash
GET /health
curl http://localhost:8004/health
```

---

## Search API (Port 8004)

### Global Search
```bash
POST /search
curl -X POST http://localhost:8004/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "customer churn rate",
    "top_k": 5,
    "filters": {
      "format": "pdf",
      "report_period": "2025-01",
      "include_multimodal": true
    }
  }'
```

### Document-Scoped Search
```bash
POST /search/within/{doc_id}
curl -X POST http://localhost:8004/search/within/d8703de2-2d5a-4b1b-8113-cfcea25deb5e \
  -H "Content-Type: application/json" \
  -d '{"query":"churn reasons","top_k":3}'
```

### Document Summary
```bash
GET /document/{doc_id}/summary
curl http://localhost:8004/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/summary
```

---

## Citation API (Port 8004)

### Generate Citations
```bash
POST /citations/generate
curl -X POST http://localhost:8004/citations/generate \
  -H "Content-Type: application/json" \
  -d '{
    "chunk_ids": [
      "e5707f3b-331e-4e36-8fd5-b3f858193dfc",
      "a2345678-1234-5678-9abc-def012345678"
    ]
  }'
```

### Preview Citation
```bash
GET /citations/preview/{doc_id}/{page_number}
curl http://localhost:8004/citations/preview/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/1
```

### Document Provenance
```bash
GET /provenance/document/{doc_id}
curl http://localhost:8004/provenance/document/d8703de2-2d5a-4b1b-8113-cfcea25deb5e
```

### Chunk Provenance
```bash
GET /provenance/chunk/{chunk_id}
curl http://localhost:8004/provenance/chunk/e5707f3b-331e-4e36-8fd5-b3f858193dfc
```

---

## Common Request/Response Formats

### Search Request
```json
{
  "query": "customer churn rate by subscription plan",
  "top_k": 5,
  "filters": {
    "doc_ids": ["doc-id-1", "doc-id-2"],
    "format": "pdf",
    "report_period": "2025-01",
    "report_series": "monthly_churn",
    "include_multimodal": true
  }
}
```

### Search Response
```json
{
  "answer_chunks": [
    {
      "chunk_id": "uuid",
      "chunk_text": "Premium plan subscribers churn due to...",
      "chunk_type": "multimodal",
      "score": 0.7655,
      "page_number": 1,
      "doc_id": "uuid",
      "filename": "CustomerChurn_Jan2025.pdf",
      "bounding_box": {"x0": 72.0, "y0": 100.5, "x1": 540.0, "y1": 650.0}
    }
  ],
  "citations": [
    {
      "label": "CustomerChurn_Jan2025.pdf, page 1",
      "page_number": 1,
      "doc_id": "uuid",
      "filename": "CustomerChurn_Jan2025.pdf",
      "chunk_type": "multimodal",
      "deep_link": "http://localhost:8004/image/uuid/1",
      "chunk_id": "uuid"
    }
  ],
  "query_metadata": {
    "docs_searched": 3,
    "response_time_ms": 245,
    "top_k": 5,
    "filters_applied": {...},
    "cached": false
  }
}
```

### Document Status Response
```json
{
  "doc_id": "uuid",
  "filename": "document.pdf",
  "format": "pdf",
  "status": "EMBEDDED",
  "page_count": 15,
  "chunk_count": 22,
  "processing_started_at": "2026-03-08T10:48:10.500Z",
  "processing_completed_at": "2026-03-08T10:48:42.800Z"
}
```

---

## Status Codes

| Status | Description |
|--------|-------------|
| **UPLOADED** | File uploaded to GCS, pending processing |
| **PROCESSING** | Classification and chunking in progress |
| **CLASSIFIED** | Page types detected, pending embedding |
| **EMBEDDED** | Ready for search (final state) |
| **ERROR** | Processing failed (check error_message) |

---

## Chunk Types

| Type | Description | Example |
|------|-------------|---------|
| **text** | Plain text chunks | Paragraphs, narrative sections |
| **table** | Extracted as markdown table | Tabular data from PDF/Excel |
| **multimodal** | Gemini Vision description + image | Charts, graphs, screenshots |

---

## Search Filters

| Filter | Type | Description | Example |
|--------|------|-------------|---------|
| **doc_ids** | list[str] | Restrict to specific documents | `["uuid1", "uuid2"]` |
| **format** | str | File format | `"pdf"`, `"xlsx"`, `"yaml"` |
| **report_period** | str | YYYY-MM format | `"2025-01"` |
| **report_series** | str | Report category | `"monthly_churn"` |
| **include_multimodal** | bool | Include vision-based chunks | `true` or `false` |

---

## Environment Variables (Key)

```bash
# AI Models
EMBEDDING_MODEL=models/gemini-embedding-001
VISION_MODEL=gemini-2.0-flash

# API Authentication
GOOGLE_API_KEY=your_api_key_here

# Database
MONGODB_URI=mongodb://mongo:27017/ragfl?replicaSet=rs0

# Storage
GCS_ENDPOINT=http://fake-gcs:4443  # Dev
GCS_BUCKET=rag-fl-documents

# Cache
REDIS_URL=redis://redis:6379

# CORS
CORS_ORIGINS=http://localhost:3001,http://127.0.0.1:3001

# Frontend URLs
NEXT_PUBLIC_RAG_FL_API=http://localhost:8004
NEXT_PUBLIC_INGESTION_API=http://localhost:8001
```

---

## Docker Commands

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f rag-fl
docker compose logs -f ingestion

# Restart service
docker compose restart rag-fl

# Rebuild after code changes
docker compose up -d --build rag-fl

# Stop all services
docker compose down

# Check status
docker compose ps

# Clean everything (DANGER: deletes data)
docker compose down -v
```

---

## MongoDB Quick Queries

```bash
# Connect to MongoDB
docker exec -it ragfl-mongo mongosh ragfl

# Count documents
db.documents.countDocuments()
db.doc_embeddings.countDocuments()

# Find by doc_id
db.documents.findOne({doc_id: "your-doc-id"})

# Find by status
db.documents.find({status: "EMBEDDED"})

# Get chunk by type
db.doc_embeddings.find({chunk_type: "multimodal"}).limit(1)

# Delete document and chunks
db.documents.deleteOne({doc_id: "doc-id"})
db.page_profiles.deleteMany({doc_id: "doc-id"})
db.doc_embeddings.deleteMany({doc_id: "doc-id"})
```

---

## Testing Workflow

```bash
# 1. Upload document
DOC_ID=$(curl -s -X POST http://localhost:8001/ingest \
  -F "file=@test.pdf" | jq -r '.doc_id')

# 2. Wait for processing
while true; do
  STATUS=$(curl -s http://localhost:8004/document/$DOC_ID/status | jq -r '.status')
  echo "Status: $STATUS"
  [[ "$STATUS" == "EMBEDDED" ]] && break
  sleep 2
done

# 3. Search
curl -s -X POST http://localhost:8004/search \
  -H "Content-Type: application/json" \
  -d '{"query":"test query","top_k":3}' | jq '.answer_chunks[0]'

# 4. View in UI
open http://localhost:3001
```

---

## Error Codes

| HTTP | Meaning | Common Cause |
|------|---------|--------------|
| 400 | Bad Request | Invalid JSON, missing required fields |
| 404 | Not Found | doc_id doesn't exist |
| 422 | Validation Error | Pydantic schema mismatch |
| 500 | Server Error | Gemini API failure, MongoDB down |

---

## Performance Benchmarks

| Operation | Expected Time |
|-----------|---------------|
| Upload (5MB PDF) | < 1s |
| Classification (15 pages) | 2-3s |
| Vision call (per page) | ~1s |
| Embedding (22 chunks) | 1-2s |
| **Total (15-page doc)** | **20-30s** |
| Search (cached) | < 50ms |
| Search (uncached) | 200-500ms |

---

## Support

- **Docs:** `rag-fl/docs/phase_summaries/INTEGRATION_GUIDE.md`
- **Architecture:** `rag-fl/ARCHITECTURE.md`
- **Logs:** `docker compose logs -f <service>`
- **MongoDB UI:** http://localhost:8081 (admin/pass)

---

**Quick Reference Version:** 1.0
**Generated:** 2026-03-08
