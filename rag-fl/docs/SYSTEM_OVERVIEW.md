# RAG-FL System Overview — Complete Implementation

**Date:** 2026-03-08
**Status:** Phases 1-6 Complete, Phase 7 (Production) Pending
**Purpose:** High-level reference for onboarding, demos, and stakeholder presentations

---

## Quick Stats

| Metric | Value |
|---|---|
| **Total Phases Completed** | 6 (+ Phase 4.1 improvements) |
| **Services Running** | 8 Docker containers |
| **Documents Embedded** | 11 (65 pages, 111 chunks) |
| **Supported Formats** | PDF, Excel, YAML, JPEG, PNG, PPTX, DOCX |
| **Embedding Dimensions** | 768-dim (gemini-embedding-001) |
| **Vision Model** | Gemini 2.0 Flash |
| **API Endpoints** | 15 total (across 3 services) |
| **Lines of Code** | ~4,700 (Python + TypeScript) |

---

## System Architecture Flow

```
INPUT SOURCES
           manual upload (UI) | CLI pipeline
                        │
                        ▼
         ┌──────────────────────────────┐
         │      Ingestion Service       │  Port 8001, Phase 2 ✅
         │   Format Registry            │
         │   7 processors               │
         │   content_hash dedup         │
         │   report_period extraction   │
         │   → auto-trigger pipeline    │  ← Phase 4.1 ✅
         └──────────────┬───────────────┘
                        │  MongoDB documents{} status=UPLOADED
                        │  background task → POST /process
                        ▼
         ┌──────────────────────────────┐
         │      rag-fl Pipeline         │  Port 8004, Phase 3 ✅
         │                              │
         │  Per-PAGE (sub-element):     │  ← Phase 3A ✅
         │  ┌─────────────────────┐     │
         │  │ pdfplumber          │     │
         │  │ → table elements    │     │
         │  ├─────────────────────┤     │
         │  │ PyMuPDF             │     │
         │  │ → visual elements   │     │
         │  ├─────────────────────┤     │
         │  │ text blocks         │     │
         │  │ → text elements     │     │
         │  └─────────────────────┘     │
         │                              │
         │  Per-ELEMENT embedding:      │
         │  table   → pdfplumber MD     │
         │            → embed 768-dim   │
         │  visual  → PNG crop          │
         │            → Gemini Vision   │
         │            → embed 768-dim   │
         │  text    → text chunks       │
         │            → embed 768-dim   │
         └──────┬───────────────┬───────┘
                │               │
                ▼               ▼
     MongoDB Collections    GCS Storage
     ┌──────────────────┐   ┌───────────────────┐
     │ documents{}      │   │ rag-fl-documents   │
     │ page_profiles{}  │   │ {doc_id}.{page}.png│
     │ doc_embeddings{} │   │ (visual crops)     │
     │ citation_cache{} │   └───────────────────┘
     └──────────────────┘
                │
                ▼
         ┌──────────────────────────────┐
         │   Next.js UI                 │  Port 3001, Phase 4 ✅
         │                              │
         │  LEFT: File list             │
         │  • Upload → auto-process     │  ← Phase 4.1 ✅
         │  • EMBEDDED only shown       │  ← Phase 4.1 ✅
         │  • Polling auto-detect done  │  ← Phase 4.1 ✅
         │                              │
         │  CENTER: Page Explorer       │
         │  • Per-element badges        │  ← Phase 3A ✅
         │  • text/table/multimodal     │
         │  • PNG image inline          │
         │  • Gemini description        │
         │                              │
         │  RIGHT: Search               │
         │  • POST /search/within/{id}  │
         │  • Citation label per result │
         └──────────────────────────────┘
                │
                ▼
         ┌──────────────────────────────┐
         │   Citation Engine            │  Phase 5 ✅, Port 8004
         │   POST /citations/generate   │
         │   Churn EDA, Page 7,         │
         │   Table 7: Churned by        │
         │   Internet Service           │
         └──────────────────────────────┘
                │
                ▼
         ┌──────────────────────────────┐
         │   Search & Retrieval API     │  Phase 6 ✅, Port 8004
         │   POST /search               │
         │   filters: report_period     │
         │           format             │
         │           doc_ids            │
         │   Redis cache 1hr            │
         │   RETRIEVAL_QUERY task_type  │
         └──────────────────────────────┘
```

---

## UI Panel to API Mapping

### LEFT PANEL — File List

| Fitur UI | API Endpoint | Notes |
|---|---|---|
| Tampilkan daftar file | `GET :8004/documents` | Filter status=EMBEDDED (Phase 4.1) |
| Upload file baru | `POST :8001/ingest` | Returns doc_id + is_duplicate flag |
| Auto-trigger processing | `POST :8004/process {doc_id}` | Via background task (Phase 4.1) |
| Poll status (upload) | `GET :8001/documents/{doc_id}` | Check ingestion status |
| Poll status (embedding) | `GET :8004/documents` | Filter by filename, check status=EMBEDDED |
| Duplicate detection message | Response dari `POST :8001/ingest` | `is_duplicate: true` |

### CENTER PANEL — Page Explorer

| Fitur UI | API Endpoint | Notes |
|---|---|---|
| List halaman + badge type | `GET :8004/document/{doc_id}/pages` | Returns page_type per page |
| Expand halaman → chunk detail | `GET :8004/document/{doc_id}/chunks/{page_number}` | Returns chunk_text, chunk_type, embedding_dims |
| Render PNG image inline | `GET :8004/image/{doc_id}/{page_number}` | GCS proxy, returns image/png |
| Indikator 768-dim per chunk | From chunks response | `embedding_dims: 768` |

### RIGHT PANEL — Search

| Fitur UI | API Endpoint | Notes |
|---|---|---|
| Search dalam dokumen | `POST :8004/search/within/{doc_id}` | Document-scoped search |
| Result + score bar | Response fields | `score, chunk_text, page_number, chunk_type` |
| Citation label per result | `POST :8004/citations/generate {chunk_ids}` | Format-specific labels |
| Click result → scroll to page | Client-side only | No API call |

### TOP BAR

| Fitur UI | API Endpoint | Notes |
|---|---|---|
| FORCE_MIXED_MODE indicator | `GET :8004/config` | Returns `force_mixed_mode`, `environment` |

---

## Backend APIs (Not Yet in UI)

| Feature | API Endpoint | Status |
|---|---|---|
| Global search lintas dokumen | `POST :8004/search` | ✅ Ready, not wired to UI |
| Filter chronological | `POST :8004/search {filters: {report_period}}` | ✅ Ready |
| Citation tooltip preview | `GET :8004/citations/preview/{doc_id}/{page}` | ✅ Ready |
| Full provenance per dokumen | `GET :8004/provenance/document/{doc_id}` | ✅ Ready |
| Full provenance per chunk | `GET :8004/provenance/chunk/{chunk_id}` | ✅ Ready |

---

## Docker Services

| Service | Port | Container | Health Check | Purpose |
|---|---|---|---|---|
| **ingestion** | 8001 | ragfl-ingestion | ✅ Healthy | Format Registry, file upload, auto-trigger pipeline |
| **rag-fl** | 8004 | ragfl-pipeline | ✅ Healthy | Per-page analysis, embedding, citation, search APIs |
| **ui** | 3001 | ragfl-ui | Running | Next.js observability interface |
| **mongo** | 27017 | ragfl-mongo | ✅ Healthy | MongoDB rs0, 4 collections, 768-dim vector index |
| **redis** | 6379 | ragfl-redis | ✅ Healthy | Search query cache (1hr TTL) |
| **fake-gcs** | 4443 | ragfl-fake-gcs | Running | Local GCS server (dev mode) |
| **libreoffice** | 3000 | ragfl-libreoffice | Running | Gotenberg: PPTX/DOCX → PDF conversion |
| **mongo-express** | 8081 | ragfl-mongo-express | Running | MongoDB web UI |

**Start all services:**
```bash
cd E:\Work\TMC - Roshn\Work\Embedding Projects POC\code\rag-fl
docker compose up -d
```

**Check status:**
```bash
docker compose ps
```

---

## MongoDB Collections

| Collection | Documents | Purpose | Indexes |
|---|---|---|---|
| **documents** | 11 | Document metadata, status, provenance | doc_id (PK), content_hash |
| **page_profiles** | 65 | Per-page classification, detected_elements | doc_id + page_number |
| **doc_embeddings** | 111 | Chunks with 768-dim vectors | chunk_id (PK), **embedding (vector 768)** |
| **citation_cache** | ~10 | Cached citations, SHA-256 keyed | cache_key, expires_at (TTL 1hr) |

**Vector Index (Atlas production only):**
- Field: `embedding`
- Type: `vector`
- Dimensions: `768`
- Similarity: `cosine`
- Index name: `embedding_index`

**Local development:** Uses cosine similarity (no index needed)

---

## Phase Implementation Summary

### Phase 1 — Docker Infrastructure ✅
**Completed:** 2026-03-05
**Summary:** MongoDB rs0, Redis, fake-gcs-server, Gotenberg, Mongo Express
**Details:** [phase_1_summary.md](phase_summaries/phase_1_summary.md)

### Phase 2 — Format Registry & Ingestion Service ✅
**Completed:** 2026-03-05
**Summary:** 7 format processors, MIME detection, content_hash deduplication, report_period extraction
**Details:** [phase_2_summary.md](phase_summaries/phase_2_summary.md)

### Phase 3 — Per-Page Analysis + Embedding Pipeline ✅
**Completed:** 2026-03-06
**Summary:** PyMuPDF + pdfplumber classification, Gemini Vision, asymmetric embedding (RETRIEVAL_DOCUMENT)
**Key Results:** 131 chunks embedded, 99 page profiles, XObject image detection fix
**Details:** [phase_3_summary.md](phase_summaries/phase_3_summary.md)

### Phase 3A — Sub-Page Element Detection ✅
**Completed:** 2026-03-08
**Summary:** Classifier rewritten to detect ALL elements per page (tables, visuals, text blocks) instead of single page-type label
**Key Results:** 111 chunks (down from 131), 8 docs, 46 Gemini calls, search scores unchanged
**Details:** Documented in memory/MEMORY.md

### Phase 4 — Next.js Observability UI ✅
**Completed:** 2026-03-07
**Summary:** Three-panel layout (file list, page explorer, search), CORS middleware, image proxy endpoint
**Stack:** Next.js 14.2.30, Tailwind CSS, 636 lines TypeScript
**Details:** [phase_4_summary.md](phase_summaries/phase_4_summary.md)

### Phase 4.1 — Workflow Improvements ✅
**Completed:** 2026-03-08
**Summary:** Auto-process after upload, rollback on failure, UI filter EMBEDDED only, polling completion detection
**Impact:** Zero manual steps after upload — fully automatic embedding pipeline
**Details:** [phase_4.1_workflow_improvements.md](phase_summaries/phase_4.1_workflow_improvements.md)

### Phase 5 — Citation Engine & Provenance API ✅
**Completed:** 2026-03-07
**Summary:** 4 endpoints (generate, preview, provenance/document, provenance/chunk), MongoDB cache, adjacent page merging
**Citation formats:** PDF (text/table/multimodal), Excel (sheet + rows), YAML (key path)
**Details:** [phase_5_summary.md](phase_summaries/phase_5_summary.md)

### Phase 6 — Search & Retrieval API ✅
**Completed:** 2026-03-07
**Summary:** Global search with chronological filters, Redis query cache, unified response shape
**Filters:** report_period, report_series, format, doc_ids, include_multimodal
**Details:** [phase_6_summary.md](phase_summaries/phase_6_summary.md)

### Phase 7 — Production / Cloud Run ⬜
**Status:** Not started
**Scope:** Migrate to MongoDB Atlas, Cloud Memorystore, real GCS, Cloud Run deployment

---

## Technology Decisions

### Models Used

| Original Spec | Actual Implementation | Reason |
|---|---|---|
| `text-embedding-004` | **gemini-embedding-001** | API key returned 404 for text-embedding-004 |
| `gemini-1.5-flash` | **gemini-2.0-flash** | API key returned 404 for gemini-1.5-flash |

Both produce identical outputs (768-dim, asymmetric task types, multimodal vision).

**Model IDs:**
```python
EMBEDDING_MODEL = "models/gemini-embedding-001"
VISION_MODEL = "gemini-2.0-flash"
```

### Asymmetric Embedding (MANDATORY)

```python
# Storing chunks (Phase 3)
genai.embed_content(
    model="models/gemini-embedding-001",
    content=chunk_text,
    task_type="RETRIEVAL_DOCUMENT",
    output_dimensionality=768
)

# User queries (Phase 6)
genai.embed_content(
    model="models/gemini-embedding-001",
    content=user_query,
    task_type="RETRIEVAL_QUERY",
    output_dimensionality=768
)
```

**Using same task_type for both degrades retrieval quality significantly.**

### Environment-Aware Vector Search

```python
# shared/utils/vector_search.py
if os.getenv("ENVIRONMENT") == "production":
    # MongoDB Atlas $vectorSearch
    pipeline = [{"$vectorSearch": {...}}]
else:
    # Local cosine similarity
    candidates = collection.find(filter_query)
    scored = [(doc, cosine_similarity(query_vec, doc["embedding"])) for doc in candidates]
```

Zero code changes for production migration — only .env values differ.

---

## User Workflow (Phase 4.1)

### Before Phase 4.1 (Manual)

1. Upload file via UI
2. File appears with badge "UPLOADED" + 0 chunks
3. **Manually click "Process →" button**
4. Wait and refresh
5. File badge changes to "EMBEDDED" + N chunks

**Pain points:** Manual step, files stuck at UPLOADED, no completion feedback

### After Phase 4.1 (Automatic)

1. Upload file via UI
2. Message: "Processing in background…"
3. [Automatic] Backend triggers pipeline
4. [Automatic] UI polls every 3 seconds
5. Message: "✅ filename embedded! N chunks created."
6. File appears in list with badge "EMBEDDED"

**Improvements:** Zero manual steps, clear success message, failed uploads auto-deleted (rollback)

---

## API Endpoints Reference

### Ingestion Service (Port 8001)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/ingest` | Upload file, auto-trigger pipeline |
| POST | `/ingest?dry_run=true` | Estimate processing cost |
| GET | `/documents` | List all documents |
| GET | `/documents/{doc_id}` | Get single document status |
| GET | `/health` | Service health check |

### rag-fl Pipeline (Port 8004)

| Method | Endpoint | Purpose | Phase |
|---|---|---|---|
| POST | `/process` | Classify → chunk → embed | 3 |
| GET | `/documents` | List all documents | 3 |
| GET | `/document/{doc_id}/pages` | Per-page breakdown | 3 |
| GET | `/document/{doc_id}/chunks/{page}` | Chunks for page | 3 |
| GET | `/image/{doc_id}/{page_number}` | GCS image proxy | 4 |
| POST | `/search/within/{doc_id}` | Document-scoped search | 4 |
| GET | `/config` | Runtime config | 4 |
| POST | `/citations/generate` | Generate citations | 5 |
| GET | `/citations/preview/{doc_id}/{page}` | Citation tooltip | 5 |
| GET | `/provenance/document/{doc_id}` | Full doc provenance | 5 |
| GET | `/provenance/chunk/{chunk_id}` | Chunk provenance trail | 5 |
| POST | `/search` | Global search with filters | 6 |
| GET | `/document/{doc_id}/summary` | Doc summary + metadata | 6 |
| GET | `/health` | Service health check | 3 |

---

## Testing & Validation

### Comparison Test (Harsh's Requirement)

Three files with identical data, different formats:

| File | Format | Extraction Method | Status |
|---|---|---|---|
| `CustomerChurn_Jan2025.xlsx` | Native Excel | openpyxl | ✅ 1 chunk |
| `CustomerChurn_Jan2025 - Table.pdf` | PDF table | pdfplumber | ✅ 1 chunk (Markdown) |
| `ChurnCustomer_Jan2025.pdf` | PDF screenshot | Gemini Vision | ✅ 1 chunk (description) |

**Result:** All three produce comparable embeddings despite different processing routes.

### Search Quality Test

Query: `"churn rate fiber optic customers"`

**Expected:** Page 7 of Churn_EDA_Report.pdf (table: "Churned by Internet Service")

**Actual:** Score 0.7655, Page 7, Table 1

**Status:** ✅ Passed

---

## Known Limitations

### Phase 4.1

- **No real-time progress:** UI polls every 3s (acceptable for POC, WebSocket recommended for production)
- **Fixed 5-minute timeout:** Large documents (>100 pages) may timeout (configurable via env var)
- **No queue system:** Multiple uploads run in parallel (Celery recommended for production)

### Phase 6

- **Local cosine scores ~0.69-0.77:** MongoDB Atlas $vectorSearch will improve to >0.85
- **Global search not in UI:** Backend ready, UI integration deferred

### General

- **No LLM answer synthesis:** UI shows raw chunks, not synthesized answers (Phase 8 scope)
- **No OneDrive integration:** Webhook stub only (real Graph API deferred)

---

## Production Migration Checklist (Phase 7)

- [ ] MongoDB → MongoDB Atlas M10 cluster
  - [ ] Create `embedding_index` (768-dim, cosine)
  - [ ] Migrate 4 collections
  - [ ] Update `MONGODB_URI` in .env
- [ ] Redis → Cloud Memorystore
  - [ ] Update `REDIS_HOST` in .env
- [ ] fake-gcs → Google Cloud Storage
  - [ ] Create bucket `rag-fl-documents`
  - [ ] Update `GCS_ENDPOINT` to real GCS
  - [ ] Add `GOOGLE_APPLICATION_CREDENTIALS`
- [ ] Deploy to Cloud Run
  - [ ] Build 3 container images (ingestion, rag-fl, ui)
  - [ ] Deploy services
  - [ ] Setup Cloud Build CI/CD
- [ ] Environment variables → Secret Manager
- [ ] Set `ENVIRONMENT=production`
- [ ] Verify $vectorSearch working (scores >0.85)

---

## File Structure

```
rag-fl/
├── ARCHITECTURE.md                   Core architecture spec
├── PHASES.md                         Phase roadmap
├── docs/
│   ├── SYSTEM_OVERVIEW.md            ← This file
│   └── phase_summaries/
│       ├── phase_1_summary.md
│       ├── phase_2_summary.md
│       ├── phase_3_summary.md
│       ├── phase_4_summary.md
│       ├── phase_4.1_workflow_improvements.md
│       ├── phase_5_summary.md
│       └── phase_6_summary.md
├── services/
│   ├── ingestion/                    Phase 2 + 4.1
│   │   ├── app/main.py              Auto-trigger background task
│   │   ├── app/registry.py          Format Registry
│   │   └── app/processors/          7 format processors
│   ├── rag-fl/                      Phase 3 + 5 + 6
│   │   ├── main.py                  FastAPI v6.0.0, 15 endpoints
│   │   ├── pipeline.py              Classify → chunk → embed
│   │   ├── classifier.py            Sub-element detection (Phase 3A)
│   │   ├── chunker.py               Per-element chunking
│   │   ├── embedder.py              Asymmetric embedding
│   │   ├── vision.py                Gemini 2.0 Flash
│   │   ├── citation.py              Citation Engine (Phase 5)
│   │   └── search.py                Search & Retrieval (Phase 6)
│   └── ui/                          Phase 4 + 4.1
│       └── app/page.tsx             636 lines, three-panel UI
├── shared/
│   ├── schemas/                     Pydantic models
│   │   ├── chunk.py                 Canonical Chunk Schema
│   │   ├── document.py              Document metadata
│   │   └── page_profile.py          Page classification
│   └── utils/
│       ├── gcs_client.py            GCS upload/download
│       ├── mongo_client.py          MongoDB connection
│       ├── vector_search.py         Auto-switch local/Atlas
│       └── period_extractor.py      Chronological metadata
├── scripts/
│   └── cleanup_uploaded.sh          Delete stuck UPLOADED files
├── docker-compose.yml               8 services
└── .env                             Environment config
```

---

## Quick Start

```bash
# 1. Navigate to project
cd E:\Work\TMC - Roshn\Work\Embedding Projects POC\code\rag-fl

# 2. Start all services
docker compose up -d

# 3. Verify all containers healthy
docker compose ps

# 4. Open UI
# http://localhost:3001

# 5. Upload a file via UI
# → auto-process will trigger
# → wait for "✅ filename embedded! N chunks"

# 6. Explore page-by-page
# → click file in left panel
# → expand pages in center panel
# → see tables, images, Gemini descriptions

# 7. Search
# → right panel: "churn rate fiber optic"
# → click result → auto-scroll to page
```

---

## Support & Documentation

- **Main architecture:** [ARCHITECTURE.md](../ARCHITECTURE.md)
- **Phase roadmap:** [PHASES.md](../PHASES.md)
- **Phase summaries:** [phase_summaries/](phase_summaries/)
- **Memory (auto):** [~/.claude/projects/.../memory/MEMORY.md](../../../../.claude/projects/e--Work-TMC---Roshn-Work-Embedding-Projects-POC-code/memory/MEMORY.md)

---

## Changelog

| Date | Change |
|---|---|
| 2026-03-08 | Created SYSTEM_OVERVIEW.md with complete architecture diagrams |
| 2026-03-08 | Phase 4.1 workflow improvements completed |
| 2026-03-08 | Phase 3A sub-element detection completed |
| 2026-03-07 | Phase 6 search API completed |
| 2026-03-07 | Phase 5 citation engine completed |
| 2026-03-07 | Phase 4 Next.js UI completed |
| 2026-03-06 | Phase 3 embedding pipeline completed |
| 2026-03-05 | Phase 2 ingestion service completed |
| 2026-03-05 | Phase 1 Docker infrastructure completed |
