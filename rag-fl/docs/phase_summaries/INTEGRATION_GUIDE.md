# RAG-FL Integration Guide
**Version:** 6.1.0
**Last Updated:** 2026-03-10
**Target Audience:** Developers integrating with RAG-FL system

---

## Table of Contents
1. [System Overview](#system-overview)
2. [Quick Start](#quick-start)
3. [Environment Configuration](#environment-configuration)
4. [API Endpoints Reference](#api-endpoints-reference)
5. [Data Integration Guide](#data-integration-guide)
6. [Frontend Integration](#frontend-integration)
7. [Testing & Verification](#testing--verification)
8. [Troubleshooting](#troubleshooting)

---

## 1. System Overview

### Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                        RAG-FL System                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐            │
│  │ Ingestion  │───▶│  RAG-FL    │───▶│  Next.js   │            │
│  │  Service   │    │  Pipeline  │    │     UI     │            │
│  │  :8001     │    │   :8004    │    │   :3001    │            │
│  └────────────┘    └────────────┘    └────────────┘            │
│         │                  │                                     │
│         │                  │                                     │
│         ▼                  ▼                                     │
│  ┌────────────┐    ┌────────────┐    ┌────────────┐            │
│  │   MongoDB  │    │   Redis    │    │  Fake GCS  │            │
│  │   :27017   │    │   :6379    │    │   :4443    │            │
│  └────────────┘    └────────────┘    └────────────┘            │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Service | Port | Purpose |
|---------|------|---------|
| **Ingestion** | 8001 | File upload & format conversion |
| **RAG-FL Pipeline** | 8004 | Classification, chunking, embedding, search |
| **UI (Next.js)** | 3001 | Observability & search interface |
| **MongoDB** | 27017 | Document metadata & embeddings storage |
| **Redis** | 6379 | Search result caching (1hr TTL) |
| **Fake GCS** | 4443 | Local object storage (dev mode) |
| **Gotenberg** | 3000 | PPTX/DOCX → PDF conversion |
| **Mongo Express** | 8081 | MongoDB admin UI |

### Tech Stack
- **Backend:** FastAPI (Python 3.11)
- **Frontend:** Next.js 14.2.30 + Tailwind CSS
- **Database:** MongoDB 7.0 (replica set)
- **Cache:** Redis 7
- **AI Models:**
  - Embedding: `gemini-embedding-001` (768-dim)
  - Vision: `gemini-2.0-flash`

---

## 2. Quick Start

### Prerequisites
- Docker Desktop installed
- Google Cloud API key with Gemini API enabled
- Git (for cloning)

### Installation Steps

```bash
# 1. Clone repository
cd "E:/Work/TMC - Roshn/Work/Embedding Projects POC/code/rag-fl"

# 2. Copy environment file
cp .env.example .env

# 3. Edit .env and add your Google API key
# GOOGLE_API_KEY=your_actual_api_key_here

# 4. Start all services
docker compose up -d

# 5. Wait for health checks (30-60 seconds)
docker compose ps

# 6. Verify services
curl http://localhost:8001/health  # Ingestion
curl http://localhost:8004/health  # RAG-FL
open http://localhost:3001         # UI
```

### First Document Upload

**Option A: Via UI**
```
1. Open http://localhost:3001
2. Click "+ Upload File"
3. Select PDF/Excel/PPTX/DOCX/YAML/Image
4. Processing starts automatically
5. View results in UI
```

**Option B: Via API**
```bash
curl -X POST http://localhost:8001/ingest \
  -F "file=@/path/to/document.pdf" \
  -F "report_series=monthly_churn" \
  -F "report_period=2025-01"
```

---

## 3. Environment Configuration

### Required Variables

```bash
# ── Google Cloud API ──────────────────────────────────────
GOOGLE_API_KEY=your_google_api_key_here

# ── AI Models ─────────────────────────────────────────────
EMBEDDING_MODEL=models/gemini-embedding-001
VISION_MODEL=gemini-2.0-flash

# ── MongoDB ───────────────────────────────────────────────
MONGODB_URI=mongodb://mongo:27017/ragfl?replicaSet=rs0
MONGODB_DB=ragfl

# ── Google Cloud Storage ──────────────────────────────────
GCS_ENDPOINT=http://fake-gcs:4443  # Dev mode
GCS_BUCKET=rag-fl-documents

# ── Redis ─────────────────────────────────────────────────
REDIS_URL=redis://redis:6379

# ── Application ───────────────────────────────────────────
ENVIRONMENT=development
DRY_RUN_THRESHOLD=10

# ── CORS ──────────────────────────────────────────────────
CORS_ORIGINS=http://localhost:3001,http://127.0.0.1:3001

# ── Citations ─────────────────────────────────────────────
CITATION_RAG_FL_BASE=http://localhost:8004
CITATION_UI_BASE=http://localhost:3001

# ── UI (Next.js) ──────────────────────────────────────────
NEXT_PUBLIC_RAG_FL_API=http://localhost:8004
NEXT_PUBLIC_INGESTION_API=http://localhost:8001

# ── File System Paths (Windows) ───────────────────────────
INPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/input
OUTPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/output
```

### Production Changes

For production deployment, update these values:

```bash
# Production environment
ENVIRONMENT=production
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/ragfl
GCS_ENDPOINT=https://storage.googleapis.com
REDIS_URL=redis://production-redis-ip:6379
CORS_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com

# Public URLs (replace with real domains)
NEXT_PUBLIC_RAG_FL_API=https://api.yourdomain.com
NEXT_PUBLIC_INGESTION_API=https://ingest.yourdomain.com
CITATION_RAG_FL_BASE=https://api.yourdomain.com
CITATION_UI_BASE=https://app.yourdomain.com
```

---

## 4. API Endpoints Reference

### 4.1 Ingestion Service (Port 8001)

#### Upload Document
```http
POST /ingest
Content-Type: multipart/form-data
```

**Request:**
```bash
curl -X POST http://localhost:8001/ingest \
  -F "file=@document.pdf" \
  -F "report_series=monthly_churn" \
  -F "report_period=2025-01"
```

**Response:**
```json
{
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "filename": "document.pdf",
  "format": "pdf",
  "status": "UPLOADED",
  "message": "File uploaded. Processing in background.",
  "gcs_path": "gs://rag-fl-documents/d8703de2-2d5a-4b1b-8113-cfcea25deb5e.pdf"
}
```

#### List Documents
```http
GET /documents
```

**Response:**
```json
[
  {
    "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
    "filename": "document.pdf",
    "format": "pdf",
    "status": "EMBEDDED",
    "uploaded_at": "2026-03-08T10:48:10.123Z",
    "report_series": "monthly_churn",
    "report_period": "2025-01"
  }
]
```

#### Delete Document
```http
DELETE /document/{doc_id}
```

**Response:**
```json
{
  "status": "deleted",
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "chunks_deleted": 22,
  "gcs_images_deleted": 15
}
```

---

### 4.2 RAG-FL Pipeline Service (Port 8004)

#### Process Document
```http
POST /process
Content-Type: application/json
```

**Request:**
```bash
curl -X POST http://localhost:8004/process \
  -H "Content-Type: application/json" \
  -d '{
    "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
    "classify_only": false
  }'
```

**Response:**
```json
{
  "status": "success",
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "pages_processed": 15,
  "chunks_created": 22,
  "gemini_calls": 15,
  "embeddings_stored": 22
}
```

#### Get Document Status
```http
GET /document/{doc_id}/status
```

**Response:**
```json
{
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "filename": "document.pdf",
  "format": "pdf",
  "status": "EMBEDDED",
  "page_count": 15,
  "chunk_count": 22,
  "processing_started_at": "2026-03-08T10:48:10.500Z",
  "processing_completed_at": "2026-03-08T10:48:42.800Z"
}
```

#### Get Page Profiles
```http
GET /document/{doc_id}/pages
```

**Response:**
```json
[
  {
    "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
    "page_number": 1,
    "detected_elements": [
      {
        "type": "table",
        "bbox": [72.0, 100.5, 540.0, 650.0],
        "table_index": 0
      },
      {
        "type": "visual",
        "bbox": [72.0, 700.0, 540.0, 780.0]
      }
    ],
    "needs_vision_retry": false,
    "created_at": "2026-03-08T10:48:15.123Z"
  }
]
```

#### Get Page Chunks
```http
GET /document/{doc_id}/chunks/{page_number}
```

**Response:**
```json
[
  {
    "chunk_id": "e5707f3b-331e-4e36-8fd5-b3f858193dfc",
    "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
    "page_number": 1,
    "chunk_type": "table",
    "chunk_text": "| Customer ID | Name | Plan | Churn Status |\n|---|---|---|---|\n...",
    "chunk_index": 0,
    "bounding_box": {"x0": 72.0, "y0": 100.5, "x1": 540.0, "y1": 650.0}
  }
]
```

#### Get Page Image (GCS Proxy)
```http
GET /image/{doc_id}/{page_number}
```

Returns PNG image for multimodal pages.

---

### 4.3 Search API (Port 8004)

#### Global Search with Filters
```http
POST /search
Content-Type: application/json
```

**Request:**
```bash
curl -X POST http://localhost:8004/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "customer churn rate by subscription plan",
    "top_k": 5,
    "filters": {
      "format": "pdf",
      "report_period": "2025-01",
      "include_multimodal": true
    }
  }'
```

**Response:**
```json
{
  "answer_chunks": [
    {
      "chunk_id": "e5707f3b-331e-4e36-8fd5-b3f858193dfc",
      "chunk_text": "Premium plan subscribers churn due to 'Price too high'...",
      "chunk_type": "multimodal",
      "score": 0.7655,
      "page_number": 1,
      "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
      "filename": "CustomerChurn_Jan2025.pdf"
    }
  ],
  "citations": [
    {
      "label": "CustomerChurn_Jan2025.pdf, page 1",
      "page_number": 1,
      "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
      "filename": "CustomerChurn_Jan2025.pdf",
      "chunk_type": "multimodal",
      "deep_link": "http://localhost:8004/image/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/1",
      "chunk_id": "e5707f3b-331e-4e36-8fd5-b3f858193dfc"
    }
  ],
  "query_metadata": {
    "docs_searched": 3,
    "response_time_ms": 245,
    "top_k": 5,
    "filters_applied": {
      "format": "pdf",
      "report_period": "2025-01"
    },
    "cached": false
  }
}
```

#### Document-Scoped Search
```http
POST /search/within/{doc_id}
Content-Type: application/json
```

**Request:**
```bash
curl -X POST http://localhost:8004/search/within/d8703de2-2d5a-4b1b-8113-cfcea25deb5e \
  -H "Content-Type: application/json" \
  -d '{
    "query": "churn reasons",
    "top_k": 3
  }'
```

Same response format as global search, but limited to specified document.

#### Document Summary
```http
GET /document/{doc_id}/summary
```

**Response:**
```json
{
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "filename": "CustomerChurn_Jan2025.pdf",
  "total_chunks": 22,
  "total_pages": 15,
  "breakdown": {
    "text": 7,
    "table": 8,
    "multimodal": 7
  }
}
```

---

### 4.4 Citation & Provenance API (Port 8004)

#### Generate Citations
```http
POST /citations/generate
Content-Type: application/json
```

**Request:**
```bash
curl -X POST http://localhost:8004/citations/generate \
  -H "Content-Type: application/json" \
  -d '{
    "chunk_ids": [
      "e5707f3b-331e-4e36-8fd5-b3f858193dfc",
      "a2345678-1234-5678-9abc-def012345678"
    ]
  }'
```

**Response:**
```json
{
  "citations": [
    {
      "label": "CustomerChurn_Jan2025.pdf, page 1",
      "page_number": 1,
      "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
      "filename": "CustomerChurn_Jan2025.pdf",
      "chunk_type": "multimodal",
      "deep_link": "http://localhost:8004/image/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/1",
      "chunk_id": "e5707f3b-331e-4e36-8fd5-b3f858193dfc"
    }
  ],
  "cached": false
}
```

#### Preview Citation
```http
GET /citations/preview/{doc_id}/{page_number}
```

**Response:**
```json
{
  "label": "CustomerChurn_Jan2025.pdf, page 1",
  "deep_link": "http://localhost:8004/image/d8703de2-2d5a-4b1b-8113-cfcea25deb5e/1",
  "chunk_type": "multimodal"
}
```

#### Document Provenance
```http
GET /provenance/document/{doc_id}
```

**Response:**
```json
{
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "filename": "CustomerChurn_Jan2025.pdf",
  "format": "pdf",
  "uploaded_at": "2026-03-08T10:48:10.123Z",
  "processing_completed_at": "2026-03-08T10:48:42.800Z",
  "total_chunks": 22,
  "embedding_model": "models/gemini-embedding-001",
  "vision_calls_made": 15
}
```

#### Chunk Provenance
```http
GET /provenance/chunk/{chunk_id}
```

**Response:**
```json
{
  "chunk_id": "e5707f3b-331e-4e36-8fd5-b3f858193dfc",
  "doc_id": "d8703de2-2d5a-4b1b-8113-cfcea25deb5e",
  "filename": "CustomerChurn_Jan2025.pdf",
  "page_number": 1,
  "chunk_type": "multimodal",
  "chunk_index": 0,
  "bounding_box": {"x0": 72.0, "y0": 100.5, "x1": 540.0, "y1": 650.0},
  "format_provenance": {
    "original_format": "pdf",
    "visual_index": 0
  },
  "embedding_model": "models/gemini-embedding-001",
  "created_at": "2026-03-08T10:48:11.370Z"
}
```

---

### 4.5 Configuration API

#### Get Runtime Config
```http
GET /config
```

**Response:**
```json
{
  "force_mixed_mode": "false",
  "environment": "development",
  "dry_run_threshold": 10
}
```

---

## 5. Data Integration Guide

### 5.1 Dummy Data vs Real Data

**Current Setup (Dummy Data):**
- Sample PDFs in `rag-fl/tests/sample-docs/`
- Fake GCS storage (local filesystem)
- Development MongoDB (no backups)

**Migrating to Real Data:**

#### Step 1: Prepare Real Documents
```bash
# Place real documents in INPUT_DIR
# Update .env:
INPUT_DIR=E:/Work/TMC - Roshn/Production/Documents
```

#### Step 2: Update Environment for Production

```bash
# .env changes for real data
ENVIRONMENT=production

# Use real Google Cloud Storage
GCS_ENDPOINT=https://storage.googleapis.com
GCS_BUCKET=your-production-bucket

# Use MongoDB Atlas (production)
MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net/ragfl

# Use Cloud Memorystore (Redis)
REDIS_URL=redis://production-ip:6379
```

#### Step 3: Clean Existing Data (if needed)
```bash
# Remove all dummy documents and embeddings
docker exec ragfl-mongo mongosh ragfl --eval "
  db.documents.deleteMany({});
  db.page_profiles.deleteMany({});
  db.doc_embeddings.deleteMany({});
"
```

#### Step 4: Upload Real Documents

**Option A: Bulk Upload via Script**
```python
import requests
from pathlib import Path

INGEST_URL = "http://localhost:8001/ingest"
DOCS_DIR = Path("E:/Production/Documents")

for doc_path in DOCS_DIR.glob("*.pdf"):
    with open(doc_path, "rb") as f:
        files = {"file": (doc_path.name, f, "application/pdf")}
        data = {
            "report_series": "production_reports",
            "report_period": "2025-01"
        }
        response = requests.post(INGEST_URL, files=files, data=data)
        print(f"Uploaded {doc_path.name}: {response.json()}")
```

**Option B: UI Upload**
1. Open http://localhost:3001
2. Click "+ Upload File"
3. Select multiple files (Shift+Click)
4. Auto-processing begins

### 5.2 MongoDB Schema

**Collection: `documents`**
```javascript
{
  doc_id: "UUID",
  filename: "string",
  format: "pdf|xlsx|yaml|pptx|docx|jpeg|png",
  status: "UPLOADED|PROCESSING|CLASSIFIED|EMBEDDED|ERROR",
  gcs_path: "gs://bucket/doc_id.ext",
  file_size_bytes: 12345,
  page_count: 15,
  uploaded_at: ISODate,
  report_series: "monthly_churn",
  report_period: "2025-01",
  processing_started_at: ISODate,
  processing_completed_at: ISODate,
  error_message: "string|null"
}
```

**Collection: `page_profiles`**
```javascript
{
  doc_id: "UUID",
  page_number: 1,
  page_type: "text|table|multimodal|mixed|full_page_image|skip",  // NEW: Phase 3F
  detected_elements: [
    {type: "table", bbox: [x0,y0,x1,y1], table_index: 0},
    {type: "visual", bbox: [x0,y0,x1,y1]},
    {type: "text", bbox: [x0,y0,x1,y1], char_count: 500},
    {type: "full_page_image", bbox: [0,0,width,height]}  // NEW: entire page
  ],
  needs_vision_retry: false,
  created_at: ISODate
}
```

**Page Types:**
- `text` - Pure text page
- `table` - Table-only page
- `multimodal` - Single visual/chart
- `mixed` - Multiple element types (text + table, etc.)
- `full_page_image` (**NEW**) - Complex mixed content captured as single full-page image
- `skip` - No extractable content

**Collection: `doc_embeddings`**
```javascript
{
  chunk_id: "UUID",
  doc_id: "UUID",
  page_number: 1,
  bounding_box: {x0, y0, x1, y1} | null,  // null for full_page_image
  section_title: "string",
  chunk_index: 0,
  format_provenance: {
    original_format: "pdf",
    table_index: 0,     // for tables
    visual_index: 0,    // for visuals
    is_full_page: true  // NEW: for full_page_image chunks
  },
  chunk_type: "text|table|multimodal",
  chunk_text: "string",  // Gemini description for multimodal (including full_page)
  gcs_image_path: "gs://bucket/doc_id.page" | null,  // Present for full_page_image
  embedding: [768 floats],
  embedding_model: "models/gemini-embedding-001",
  embedding_task_type: "RETRIEVAL_DOCUMENT",
  created_at: ISODate,
  updated_at: ISODate
}
```

**Full-Page Image Schema (Phase 3F):**
- `chunk_type` = `"multimodal"`
- `gcs_image_path` = `"gs://rag-fl-documents/{doc_id}.{page_number}"` (full page capture)
- `chunk_text` = Comprehensive Gemini Vision description of entire page
- `bounding_box` = `null` (entire page, no bbox clip)
- `format_provenance.is_full_page` = `true`

**Collection: `citation_cache`** (TTL 1 hour)
```javascript
{
  cache_key: "sha256_hash",
  citations: [...],
  expires_at: ISODate
}
```

### 5.3 Vector Search Index (MongoDB Atlas Only)

For production deployment on MongoDB Atlas, create vector search index:

```javascript
{
  "name": "vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 768,
        "similarity": "cosine"
      },
      {
        "type": "filter",
        "path": "doc_id"
      },
      {
        "type": "filter",
        "path": "chunk_type"
      }
    ]
  }
}
```

**Note:** Local development uses cosine similarity in Python. Atlas $vectorSearch provides faster results in production.

---

## 6. Frontend Integration

### 6.1 UI Features

**Left Panel - Document List:**
- File upload button (+ Upload File)
- Document list with status badges
  - 🟢 EMBEDDED (ready for search)
  - 🟡 PROCESSING (in progress)
  - 🔴 ERROR (failed)
- Click document to view pages
- Delete button (trash icon)

**Center Panel - Page Explorer:**
- Shows pages from selected document
- Page type badges:
  - 📊 TABLE - Extracted markdown table
  - 🖼️ MULTIMODAL - Gemini vision description
  - 📝 TEXT - Plain text
  - ⏭️ SKIP - No extractable content
- Click to expand/view content

**Right Panel - Search:**
- Query input (requires document selection)
- Search results with:
  - Relevance score (0.0 - 1.0)
  - Chunk text preview
  - Page number
  - Jump to page link

### 6.2 Embedding the UI

**Standalone Deployment:**
```bash
cd services/ui
npm install
npm run dev  # Development mode (port 3001)
npm run build && npm start  # Production mode
```

**Iframe Integration:**
```html
<!-- Embed RAG-FL UI in your application -->
<iframe
  src="http://localhost:3001"
  width="100%"
  height="800px"
  frameborder="0"
></iframe>
```

**API-Only Integration:**

If you want to build your own UI, use the REST APIs directly:

```javascript
// Example: Upload document
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('report_series', 'my_reports');

const response = await fetch('http://localhost:8001/ingest', {
  method: 'POST',
  body: formData
});
const result = await response.json();
console.log('Document ID:', result.doc_id);

// Example: Search
const searchResponse = await fetch('http://localhost:8004/search', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    query: 'customer churn rate',
    top_k: 5,
    filters: {format: 'pdf', include_multimodal: true}
  })
});
const searchResults = await searchResponse.json();
console.log('Results:', searchResults.answer_chunks);
```

---

## 7. Testing & Verification

### 7.1 Health Checks

```bash
# Check all services
curl http://localhost:8001/health  # {"status":"up","service":"ingestion"}
curl http://localhost:8004/health  # {"status":"up","service":"rag-fl"}

# Check Docker containers
docker compose ps
# All should show "healthy" or "running"
```

### 7.2 End-to-End Test

```bash
# 1. Upload test document
curl -X POST http://localhost:8001/ingest \
  -F "file=@tests/sample-docs/CustomerChurn_Jan2025.pdf" \
  | jq '.doc_id'
# Save the doc_id output

# 2. Wait for processing (check status)
DOC_ID="<paste-doc-id-here>"
curl http://localhost:8004/document/$DOC_ID/status | jq '.status'
# Wait until status = "EMBEDDED"

# 3. Test search
curl -X POST http://localhost:8004/search \
  -H "Content-Type: application/json" \
  -d '{"query":"customer churn","top_k":3}' \
  | jq '.answer_chunks[0].score'
# Should return score > 0.5

# 4. Verify in UI
open http://localhost:3001
# Document should appear in left panel with EMBEDDED badge
```

### 7.3 Performance Benchmarks

**Expected Processing Times (15-page PDF):**
- Upload: < 1 second
- Classification: 2-3 seconds
- Vision calls (multimodal pages): ~1 second per page
- Embedding: 1-2 seconds for batch
- **Total:** 20-30 seconds for typical document

**Search Performance:**
- Cached queries: < 50ms
- Uncached queries: 200-500ms (local cosine)
- With Atlas $vectorSearch: < 100ms

### 7.4 Log Monitoring

```bash
# Real-time logs
docker compose logs -f ingestion  # Ingestion service
docker compose logs -f rag-fl     # RAG-FL pipeline
docker compose logs -f ui         # Next.js UI

# Filter for errors
docker compose logs rag-fl | grep ERROR
```

**Expected Log Output (Successful Processing):**
```
INFO Received document: CustomerChurn_Jan2025.pdf
INFO Classification complete: 15 pages
INFO Chunking complete: 22 chunks, 15 Gemini Vision calls
INFO Embedding 22 chunks via models/gemini-embedding-001 ...
INFO Embedding batch 1/1: 22 chunks
INFO Stored 22 chunks to MongoDB
INFO Document d8703de2... status → EMBEDDED
```

---

## 8. Troubleshooting

### Common Issues

#### Issue: "GOOGLE_API_KEY not set"
**Solution:**
```bash
# Check .env file exists and has API key
cat .env | grep GOOGLE_API_KEY

# Restart services to reload environment
docker compose restart rag-fl
```

#### Issue: MongoDB connection refused
**Solution:**
```bash
# Check MongoDB is healthy
docker compose ps mongo
# If unhealthy, restart
docker compose restart mongo

# Check replica set initialized
docker exec ragfl-mongo mongosh --eval "rs.status()"
```

#### Issue: "Vision circuit breaker OPEN"
**Cause:** 5 consecutive Gemini Vision API failures

**Solution:**
```bash
# Check API key quota/permissions
# Reset circuit breaker by restarting service
docker compose restart rag-fl
```

#### Issue: Search returns no results
**Checklist:**
1. Document status = EMBEDDED? `curl http://localhost:8004/document/$DOC_ID/status`
2. Chunks stored? `curl http://localhost:8004/document/$DOC_ID/summary`
3. Query embedding model matches storage model? (both should use `gemini-embedding-001`)

#### Issue: UI not updating after upload
**Solution:**
```bash
# Check auto-processing triggered
docker compose logs ingestion | grep "trigger_pipeline"

# Manually trigger processing
curl -X POST http://localhost:8004/process \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"<doc-id>"}'
```

### Debugging Tools

**MongoDB Shell:**
```bash
# Connect to MongoDB
docker exec -it ragfl-mongo mongosh ragfl

# Check documents
db.documents.find().pretty()
db.doc_embeddings.countDocuments()

# Check specific document
db.documents.findOne({doc_id: "your-doc-id"})
```

**Mongo Express UI:**
```
Open: http://localhost:8081
Username: admin
Password: pass
```

**Redis CLI:**
```bash
# Connect to Redis
docker exec -it ragfl-redis redis-cli

# Check cache keys
KEYS *
GET <cache-key>
TTL <cache-key>
```

---

## 9. Production Deployment Checklist

- [ ] **Environment Variables:**
  - [ ] Update `GOOGLE_API_KEY` with production key
  - [ ] Set `ENVIRONMENT=production`
  - [ ] Update `MONGODB_URI` to Atlas connection string
  - [ ] Update `GCS_ENDPOINT` to `https://storage.googleapis.com`
  - [ ] Update `REDIS_URL` to Cloud Memorystore
  - [ ] Update all `NEXT_PUBLIC_*` URLs to production domains
  - [ ] Update `CORS_ORIGINS` with production domains

- [ ] **MongoDB Atlas:**
  - [ ] Create M10+ cluster (required for $vectorSearch)
  - [ ] Create vector search index on `doc_embeddings.embedding`
  - [ ] Enable automated backups
  - [ ] Set up IP whitelist

- [ ] **Google Cloud:**
  - [ ] Create production GCS bucket
  - [ ] Set up IAM permissions (service account)
  - [ ] Enable Gemini API
  - [ ] Set up API key rotation

- [ ] **Security:**
  - [ ] Move `GOOGLE_API_KEY` to Secret Manager
  - [ ] Enable HTTPS/TLS for all services
  - [ ] Review CORS settings
  - [ ] Set up authentication/authorization
  - [ ] Enable audit logging

- [ ] **Monitoring:**
  - [ ] Set up application logging (Cloud Logging)
  - [ ] Configure error alerting
  - [ ] Monitor API quota usage
  - [ ] Set up uptime checks

- [ ] **Testing:**
  - [ ] Load test with production data volume
  - [ ] Verify search accuracy on real data
  - [ ] Test backup/restore procedures
  - [ ] Document runbooks for common issues

---

## 10. Support & Resources

### Documentation Files
- `ARCHITECTURE.md` - System architecture and design decisions
- `SYSTEM_OVERVIEW.md` - High-level system overview
- `phase_summaries/` - Detailed phase-by-phase development history

### Key Files to Review
```
rag-fl/
├── .env.example              # Environment template
├── docker-compose.yml        # Docker orchestration
├── services/
│   ├── ingestion/            # File upload service
│   │   └── app/main.py
│   ├── rag-fl/               # Core pipeline
│   │   ├── pipeline.py       # Main processing logic
│   │   ├── classifier.py     # Page element detection
│   │   ├── chunker.py        # Content extraction
│   │   ├── embedder.py       # Embedding generation
│   │   ├── search.py         # Search API
│   │   └── citation.py       # Citation engine
│   └── ui/                   # Next.js frontend
│       └── app/page.tsx
└── shared/
    ├── schemas/              # Pydantic models
    └── utils/                # MongoDB, GCS, Redis clients
```

### Contact
For integration support, refer to project documentation or reach out to the development team.

---

## 11. Recent Updates & Roadmap

### Phase 3F (2026-03-10) - Full-Page-as-Image ✅

**Problem:** Complex mixed pages (table with invisible borders + charts) hard to parse element-by-element

**Solution:** Capture entire page as single high-res image, Gemini Vision describes full context

**Implementation:**
- **Classifier:** Detects `page_type="full_page_image"` when table + visual OR complex mixed
- **Chunker:** `chunk_full_page_image()` renders full page at 3x zoom, uploads to GCS
- **Gemini Prompt:** "Describe this entire page in detail. Include all text content, tables (with data), charts, diagrams, and their relationships."
- **Result:** Single multimodal chunk with comprehensive description + full-page image

**Benefits:**
- Simplifies parsing complex layouts
- LLM gets complete page context during retrieval (not fragmented elements)
- Reduces edge cases (invisible table borders, merged cells, etc.)

**Example:**
- **Before:** Titanic page 5 → 3 chunks (table bbox, chart bbox, text bbox) - fragmented
- **After:** Titanic page 5 → 1 chunk (full page image + holistic Gemini description)

---

### Next Phase - Format Expansion & Integration

**Pending Tasks:**
1. **markitdown Integration** - Excel direct reading (no PDF conversion, supports multi-sheet)
2. **Image Format Support** - Test PNG, JPEG uploads (already coded, needs verification)
3. **YAML Format Support** - Test YAML uploads
4. **Ahmad Integration** - Connect as pluggable RAG tool, golden dataset evaluation
5. **Schema Sync** - Coordinate MongoDB schema changes with Ahmad's pipeline

**Production Readiness:**
- Phase 7: Cloud Run deployment
- MongoDB Atlas $vectorSearch index
- Real GCS bucket (replace fake-gcs)
- API authentication & rate limiting

---

**Document Version:** 1.1
**Generated:** 2026-03-10
**System Version:** 6.1.0
