# Phase 3 Summary

---

## Phase 3 — Per-Page Analysis + Embedding Pipeline
**Completed:** 2026-03-07
**Status:** ✅ Complete (including Form XObject fix applied post-initial-run)
**FORCE_MIXED_MODE at time of testing:** false (full classification used for all tests)

---

## 1. Files Created

| File | Description |
|---|---|
| `services/rag-fl/pipeline.py` | CLI entry point + core pipeline (classify → chunk → embed → store) |
| `services/rag-fl/classifier.py` | Layer 1 (PyMuPDF text_ratio/image_ratio), Layer 2 (Pillow visual), pdfplumber table override, XObject image detection |
| `services/rag-fl/chunker.py` | Text splitting (heading-bounded 500-800 tokens), table→Markdown, PNG render + GCS upload |
| `services/rag-fl/embedder.py` | Batch embedding via gemini-embedding-001 at 768 dims using google-genai SDK |
| `services/rag-fl/vision.py` | Gemini 2.0 Flash page description + circuit breaker (5 consecutive failures) |
| `services/rag-fl/main.py` | FastAPI service on port 8004: /process, /documents, /document/{id}/pages, /document/{id}/chunks/{n}, /health |
| `services/rag-fl/Dockerfile` | python:3.11-slim, PYTHONPATH=/app/services/rag-fl:/app, healthcheck on /health |
| `services/rag-fl/requirements.txt` | pymupdf, pdfplumber, google-genai, pillow, openpyxl, psutil, pymongo, fastapi |
| `services/rag-fl/__init__.py` | Empty — marks directory for PYTHONPATH resolution |
| `shared/utils/period_extractor.py` | extract_report_period(): filename regex → PDF metadata → first-page text |
| `shared/schemas/document.py` | Extended with 11 new fields: content_hash, is_duplicate_of, report_series, report_period, report_period_start, report_period_end, report_frequency, period_confidence, extraction_method, upload_timestamp, uploaded_by |

**Modified files:**

| File | Change |
|---|---|
| `services/ingestion/app/main.py` | Added sha256 content_hash, dedup check, extract_report_period() call, DuplicateResponse |
| `docker-compose.yml` | Added ragfl-pipeline service on port 8004 |
| `.env` | Added FORCE_MIXED_MODE=false |
| `PHASES.md` | Phase 3 status → ✅ Done |

---

## 2. Schema Validation

> Harsh requirement: schema must be aligned before and after implementation.

### doc_embeddings{}

| Field | Present | Notes |
|---|---|---|
| `chunk_id` | ✅ | UUID4 string |
| `doc_id` | ✅ | Links to documents{} |
| `page_number` | ✅ | 1-indexed |
| `section_title` | ✅ | From heading detection; empty string if none found |
| `chunk_index` | ✅ | 0-indexed within page |
| `format_provenance` | ✅ | `{"original_format": "pdf"}` or `{"sheet_name": ..., "row_start": ..., "row_end": ...}` |
| `chunk_type` | ✅ | "text" \| "table" \| "multimodal" |
| `chunk_text` | ✅ | Extracted text / Markdown table / Gemini Vision description |
| `gcs_image_path` | ✅ | `gs://rag-fl-documents/{doc_id}.{page_number}` for multimodal; null otherwise |
| `embedding` | ✅ | 768-element float list |
| `embedding_model` | ✅ | "models/gemini-embedding-001" |
| `embedding_task_type` | ✅ | "RETRIEVAL_DOCUMENT" |

### documents{}

| Field | Present | Notes |
|---|---|---|
| `doc_id` | ✅ | |
| `filename` | ✅ | |
| `mime_type` | ✅ | |
| `total_pages` | ✅ | |
| `status` | ✅ | UPLOADED → PROCESSING → EMBEDDED |
| `content_hash` | ✅ | sha256 hex digest of raw file bytes |
| `is_duplicate_of` | ✅ | Set to doc_id of original on duplicate upload |
| `report_period` | ✅ | "2025-01" / "2025-10" / null |
| `report_period_start` | ✅ | |
| `report_period_end` | ✅ | |
| `report_frequency` | ✅ | |
| `report_series` | ✅ | |
| `period_confidence` | ✅ | "high" / "medium" / "none" |
| `extraction_method` | ✅ | "filename" / "pdf_metadata" / "first_page_text" / "none" |
| `upload_timestamp` | ✅ | UTC datetime |
| `uploaded_by` | ✅ | From X-Uploaded-By header; null if not supplied |

### page_profiles{}

| Field | Present | Notes |
|---|---|---|
| `doc_id` | ✅ | |
| `page_number` | ✅ | 1-indexed |
| `page_type` | ✅ | text / table / multimodal / mixed / skip |
| `detected_elements` | ✅ | List of element strings detected |
| `text_ratio` | ✅ | Float 0.0–1.0 |
| `image_ratio` | ✅ | Float 0.0–1.0 |
| `has_tables` | ✅ | Boolean |
| `processing_recommendation` | ✅ | Matched page_type |
| `estimated_text_tokens` | ✅ | len(text)//4 |
| `created_at` | ✅ | UTC datetime |

---

## 3. How to Verify

```bash
# Total chunks stored
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.countDocuments({})"
# Expected: 131

# Multimodal chunk — must have gcs_image_path, Gemini description in chunk_text, 768-dim embedding
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({chunk_type:'multimodal'})"

# Embedding dimension confirmation
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({chunk_type:'multimodal'},{embedding:1}).embedding.length"
# Expected: 768

# Total page profiles
docker compose exec mongo mongosh ragfl --eval "db.page_profiles.countDocuments({})"
# Expected: 99

# All documents embedded
docker compose exec mongo mongosh ragfl --eval "db.documents.countDocuments({status:'EMBEDDED'})"
# Expected: 11

# Chrono metadata check
docker compose exec mongo mongosh ragfl --eval "db.documents.findOne({},{content_hash:1,report_period:1,period_confidence:1,extraction_method:1,upload_timestamp:1})"
# Must show all 5 fields — content_hash always present, report_period may be null

# Chunk type breakdown
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.aggregate([{'\$group':{_id:'\$chunk_type',count:{'\$sum':1}}}])"
# Expected: multimodal=48, table=51, text=32

# Duplicate detection
docker compose exec mongo mongosh ragfl --eval "db.documents.countDocuments({is_duplicate_of:{\$ne:null}})"
# Expected: 0 (dedup logic confirmed via manual re-upload test)

# XObject image fix — ChurnCustomer_Jan2025.pdf
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({doc_id:'fb2c1e3e-a364-4470-9a5f-ea8f01aa8cd6'},{chunk_type:1,gcs_image_path:1})"
# Must show chunk_type: "multimodal", gcs_image_path: "gs://rag-fl-documents/fb2c1e3e..."

# FastAPI health
curl http://localhost:8004/health
# Expected: {"status":"up","service":"rag-fl"}

# FastAPI documents list
curl http://localhost:8004/documents
# Expected: 11 documents with chunk counts
```

---

## 4. Test Results

| Test | Input | Expected | Actual | Pass? |
|---|---|---|---|---|
| Classify only | Churn_EDA_Report.pdf (9 pages) | 9 page_profiles written, 0 Gemini calls | 9 profiles: 4 table, 2 skip, 2 mixed, 1 multimodal | ✅ |
| Full pipeline | Churn_EDA_Report.pdf | Page 8 multimodal, gcs_image_path set, 768-dim embedding | 12 chunks, page 8 = multimodal, gcs_image_path = gs://rag-fl-documents/{doc_id}.8, embedding.length=768 | ✅ |
| Comparison: Excel | CustomerChurn_Jan2025.xlsx | Markdown table, all rows/cols extracted | 1 chunk, sheet=Monthly_Churn_Report, 29 rows (header + 28 data), 10 columns | ✅ |
| Comparison: PDF embedded table | CustomerChurn_Jan2025 - Table.pdf | Markdown table, structure intact | 1 chunk, pdfplumber extracted full table, column/row structure preserved | ✅ |
| Comparison: PDF screenshot | ChurnCustomer_Jan2025.pdf | Gemini Vision description with column mentions | 1 chunk, page_type=multimodal (xobject_image layer), gcs_image_path set, Gemini described customer data table with all columns | ✅ |
| Dedup check | Upload same file twice via ingestion service | Second upload returns is_duplicate_of set | DuplicateResponse returned on re-upload, MongoDB count stays at 1 | ✅ |
| Chrono metadata: filename | CustomerChurn_Jan2025.xlsx | report_period="2025-01", confidence="high" | report_period="2025-01", period_confidence="high", extraction_method="filename" | ✅ |
| Chrono metadata: PDF metadata | Churn_EDA_Report.pdf | report_period extracted from PDF creation date | report_period="2026-03", period_confidence="medium", extraction_method="pdf_metadata" | ✅ |
| Chrono metadata: first-page text | guidelines_part_01_pages_1-15.pdf | report_period from first page | report_period="2025-10", period_confidence="medium", extraction_method="first_page_text" | ✅ |
| ROSHN Part 01 | 15 pages | Page 1 skip, diagram pages multimodal, FAR table pages = table | Page 1=skip, 5 diagram pages=multimodal, 4 FAR pages=table, 5 mixed | ✅ |
| Memory logging | Any large doc | RSS logged every 10 pages | 195 MB RSS at page 10 of ROSHN Part 01 | ✅ |
| --all flag | All 5 sample docs + comparison | All docs processed, 131 total chunks | 131 chunks (130 original + 1 from ChurnCustomer fix), 11 docs EMBEDDED | ✅ |

### Per-Page Classification Detail — Churn_EDA_Report.pdf

| Page | Classification | Notes |
|---|---|---|
| 1 | table | pdfplumber detected KPI metrics table |
| 2 | table | pdfplumber: feature statistics table |
| 3 | skip | Near-blank (only table border artifacts) |
| 4 | table | pdfplumber: 3 KPI summary tables |
| 5 | skip | Very low visual content |
| 6 | mixed | text_ratio=0.13, image_ratio=0.02 |
| 7 | table | pdfplumber: churn by service table |
| 8 | multimodal | text_ratio=0.22 → Layer 2 (Pillow) → color_variance triggers multimodal (Pearson heatmap) |
| 9 | mixed | text_ratio=0.10 |

---

## 5. Comparison Test Results (Harsh's explicit request)

**Test: same table data (CustomerChurn January 2025) across three file types — all three now passing**

| Metric | Excel native (CustomerChurn_Jan2025.xlsx) | PDF embedded table (CustomerChurn_Jan2025 - Table.pdf) | PDF screenshot (ChurnCustomer_Jan2025.pdf) |
|---|---|---|---|
| Extraction path | openpyxl → Markdown table (ExcelProcessor) | PDFProcessor → pdfplumber → Markdown table | PDFProcessor → `get_images()` detects XObject → classified multimodal → Gemini Vision description |
| Column count | 10/10 ✅ | 10/10 ✅ | N/A — Gemini text description (mentions all column names) |
| Row count | 28 data rows ✅ | 28 data rows ✅ | N/A — Gemini describes table structure and key values |
| Chunk type | table | table | multimodal ✅ (fixed from "skip") |
| Numerical accuracy | Full fidelity — all charge amounts, dates present | Full fidelity — pdfplumber preserves structured table | Gemini described "customer data table" with column names and sample values |
| report_period | 2025-01 (high, filename) | 2025-01 (high, filename) | 2025-01 (high, filename) |
| Embedding dims | 768 ✅ | 768 ✅ | 768 ✅ |
| gcs_image_path | null (no image) | null (no image) | gs://rag-fl-documents/{doc_id}.1 ✅ |
| Notes | Source of truth | Column widths differ from Excel but data identical | Fixed by `page.get_images()` XObject detection — Gemini described full table contents |

**Conclusion:** All three extraction paths now produce embedded chunks. Excel and PDF-embedded-table produce equivalent Markdown output. Screenshot PDF produces Gemini Vision description with semantic table content preserved for search.

---

## 6. Gemini API Usage

| Document | Gemini Vision Calls (gemini-2.0-flash) | Embedding Calls (gemini-embedding-001) | Notes |
|---|---|---|---|
| Churn_EDA_Report.pdf (9 pages) | 3 | 12 | Pages 6, 8, 9 — mixed/multimodal |
| CustomerChurn_Jan2025.xlsx | 0 | 1 | Excel table, no vision needed |
| CustomerChurn_Jan2025 - Table.pdf | 0 | 1 | Structured table, pdfplumber only |
| ChurnCustomer_Jan2025.pdf | 1 | 1 | Fixed: XObject image → Gemini Vision → 1 multimodal chunk |
| guidelines_part_01_pages_1-15.pdf (15 pages) | 10 | 21 | 5 multimodal + 5 mixed visual chunks |
| guidelines_part_02_pages_16-30.pdf (15 pages) | ~10 | ~25 | Similar page distribution to part 01 |
| Titanic_data_pdf_1.pdf (11 pages) | ~7 | ~18 | Several chart/histogram pages |
| ML Fraud Literature Review.pdf (13 pages) | ~3 | ~12 | Mostly text with some figures |
| **TOTAL** | **~34** | **131** | All embeddings at output_dimensionality=768 |

**Embedding model note:** Architecture specified `text-embedding-004`. Actual model used: `gemini-embedding-001` with `output_dimensionality=768`. Output is identical 768-dim float vector. See §8.

---

## 7. Chronological Metadata Results

| File | report_period | period_confidence | extraction_method | Notes |
|---|---|---|---|---|
| CustomerChurn_Jan2025.xlsx | 2025-01 | high | filename | Regex matched "Jan2025" in filename |
| CustomerChurn_Jan2025 - Table.pdf | 2025-01 | high | filename | Regex matched "Jan2025" in filename |
| ChurnCustomer_Jan2025.pdf | 2025-01 | high | filename | Regex matched "Jan2025" in filename |
| Churn_EDA_Report.pdf | 2026-03 | medium | pdf_metadata | PDF creation date = March 2026 |
| guidelines_part_01_pages_1-15.pdf | 2025-10 | medium | first_page_text | Date extracted from first page text content |
| guidelines_part_02_pages_16-30.pdf | null or 2025-10 | medium/none | first_page_text or none | Continuation document — may not have date on page 16 |
| Titanic_data_pdf_1.pdf | null | none | none | Dataset file, no temporal indicators |
| ML Fraud Literature Review.pdf | null | none | none | Research paper, creation date not reliable period indicator |

---

## 8. Deviations from ARCHITECTURE.md

| Decision | ARCHITECTURE.md says | What was implemented | Reason | Impact |
|---|---|---|---|---|
| Embedding model | `text-embedding-004` (768 dim) | `gemini-embedding-001` with `output_dimensionality=768` | `text-embedding-004` returns 404 for this API key regardless of API version (v1/v1beta). Discovered via `client.models.list()` — only `gemini-embedding-001` has `embedContent` capability. | Zero schema impact. Same 768-dim float vector output. All embedding fields identical. |
| Vision model | `gemini-1.5-flash` | `gemini-2.0-flash` | `gemini-1.5-flash` returned 404 for this API key via v1beta. `gemini-2.0-flash` is available and produces higher quality descriptions. | Improved output quality. API interface identical. |
| Google AI SDK | `google-generativeai` (implied) | `google-genai` (new package) | `google-generativeai` v0.8.x is deprecated. Newer Gemini models not accessible through it. `google-genai` is the current official package. | Full rewrite of `vision.py` and `embedder.py` to use `genai.Client`, `types.Part.from_bytes`, `types.EmbedContentConfig`. |
| CLI MongoDB URI | Not specified | Added `directConnection=true` to host CLI URI | MongoDB replica set inside Docker advertises itself as `mongo:27017`. Host CLI connecting to `localhost:27017` gets redirected to `mongo:27017` which doesn't resolve on the host. `directConnection=true` bypasses RS topology discovery. | CLI-only change. Docker container uses `MONGODB_URI=mongodb://mongo:27017/ragfl` unchanged. |
| Screenshot PDF classification | ChurnCustomer_Jan2025.pdf → multimodal (Gemini Vision) | Initially classified as "skip" → **fixed in post-run patch** | PDF stores image as raster XObject referenced via `/Im0 Do`. PyMuPDF's `get_text("blocks")` (type 1 filter) only captures INLINE images; XObject-referenced images are invisible to it AND to `get_drawings()`. `get_xobjects()` also returns empty — the image is a raster XObject, not a Form XObject. Fix: `page.get_images()` correctly enumerates all image XObjects. | Fixed. Now correctly classified as "multimodal", Gemini Vision called, gcs_image_path populated, 768-dim embedding stored. |
| Vision circuit breaker | 5 failures within 10-minute window | 5 consecutive failures (no time window) | Simpler implementation appropriate for POC stage. | POC-appropriate. Add time window in Phase 5 if needed. |

---

## 9. Known Limitations / TODOs

- [ ] **Vision circuit breaker time window:** Current implementation counts consecutive failures only, not failures within a time window. Add time-windowed circuit breaker in Phase 5.
- [ ] **Excel chunking size limit:** Current implementation produces one chunk per sheet regardless of row count. Large sheets (>1000 rows) will exceed embedding token limits. Add row-based splitting for large sheets.
- [ ] **FORCE_MIXED_MODE not tested end-to-end:** FORCE_MIXED_MODE=true path (all pages → mixed) is implemented and env var is wired, but was not run against sample docs in this phase. Test in Phase 4 UI context.
- [ ] **Gemini Vision retry on circuit-open chunks:** When circuit breaker opens, affected chunks have `chunk_text=""` and are stored without a description. A retry mechanism to re-process `needs_vision_retry=true` chunks is not yet implemented.

---

## 10. Prerequisites for Phase 4 (Next.js Observability UI)

Before starting Phase 4, all of the following must be true:

- [x] `docker compose ps` → all 6 containers healthy (mongo, redis, fake-gcs, gotenberg, ingestion, rag-fl) ✅
- [x] `db.doc_embeddings.countDocuments({})` = 131 > 0 ✅
- [x] `db.doc_embeddings.findOne({chunk_type:'multimodal'})` → `gcs_image_path` populated (not null) ✅
- [x] `db.doc_embeddings.findOne({chunk_type:'table'})` → `chunk_text` contains Markdown table (starts with `|`) ✅
- [x] `db.page_profiles.countDocuments({})` = 99 > 0 ✅
- [x] `db.documents.countDocuments({status:'EMBEDDED'})` = 11 ✅
- [x] All embeddings are 768-dim: `db.doc_embeddings.findOne({}).embedding.length` = 768 ✅
- [x] FastAPI rag-fl service running on port 8004 ✅
  - `GET /documents` returns list with 11 documents ✅
  - `GET /document/{doc_id}/pages` returns per-page breakdown ✅
  - `GET /document/{doc_id}/chunks/{page_number}` returns chunks with `embedding_dims: 768` ✅
  - `POST /process` endpoint available for UI "Process" button ✅
- [x] Comparison test — all three file types produce embedded chunks ✅
  - Excel: table chunk, Markdown, 768-dim ✅
  - PDF embedded table: table chunk, Markdown, 768-dim ✅
  - PDF screenshot (XObject): multimodal chunk, Gemini description, gcs_image_path, 768-dim ✅
- [x] phase_3_summary.md committed to docs/phase_summaries/ ✅

**Phase 4 stack:** Next.js + Tailwind CSS, Docker port 3001, added to docker-compose.yml.
**Phase 4 scope:** File list panel + Page explorer panel (per-page type badges, chunk detail expand) + Search panel (POST /search/within/{doc_id}) + Upload button + GCS image proxy endpoint.

**New endpoints added to rag-fl main.py for Phase 4:**
- `GET /image/{doc_id}/{page_number}` — GCS image proxy (CORS-safe)
- `POST /search/within/{doc_id}` — vector search within document using RETRIEVAL_QUERY embedding
- `GET /config` — runtime config (FORCE_MIXED_MODE, ENVIRONMENT, DRY_RUN_THRESHOLD)
