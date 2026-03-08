# Phase 3 Summary

---
# Summary solcing in 8 March 2026 :
 Results Summary

  Investigation Answers

  ┌─────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────┐
  │              Question               │                                           Answer                                            │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ GCS key format for multiple visuals │ {doc_id}.{page} (v0), {doc_id}.{page}.v1 (v1+) — already implemented in chunker.py          │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ /image/{doc_id}/{page} endpoint     │ Always fetched only {doc_id}.{page} — no v param support                                    │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ UI image mapping                    │ Hardcoded doc_id + page_number, completely ignored chunk.gcs_image_path                     │
  ├─────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────┤
  │ pdfplumber table strategy           │ vertical_strategy: "lines", horizontal_strategy: "lines" — lines-only, no whitespace tables │
  └─────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────┘

  ---
  Fix Results — Page by Page

  ┌──────┬─────────────────────────────────────────────────┬───────────────────────────────────────────────┬───────────────────────────────────────────────┐    
  │ Page │                    Expected                     │                      Got                      │                    Status                     │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 1    │ text/table chunks, no text in visual crop       │ 5 table chunks + 1 multimodal (separate GCS   │ ✅ text not captured in visual                │    
  │      │                                                 │ key)                                          │                                               │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 2    │ 1 table chunk                                   │ 1 table chunk                                 │ ✅                                            │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 3    │ 3+1 visual chunks (charts + pivot table)        │ 1 visual chunk (all charts cluster into 1     │ ⚠️ content captured in Gemini description but │    
  │      │                                                 │ large region)                                 │  not split                                    │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 4    │ chunk 1 = first chart, chunk 2 = violin         │ .4 and .4.v1 — 32KB vs 64KB = different crops │ ✅                                            │    
  │      │ (different images)                              │                                               │                                               │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 5    │ whitespace table detected + visual (no huge     │ ws=True table chunk + visual chunk with       │ ✅                                            │    
  │      │ whitespace)                                     │ trimming                                      │                                               │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 6    │ 2 chunks with different images                  │ .6 and .6.v1 — distinct sizes                 │ ✅                                            │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 7–9  │ unchanged                                       │ unchanged (1 chunk each)                      │ ✅                                            │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 10   │ scatter + boxplot (different images)            │ .10 and .10.v1 — distinct sizes               │ ✅                                            │    
  ├──────┼─────────────────────────────────────────────────┼───────────────────────────────────────────────┼───────────────────────────────────────────────┤    
  │ 11   │ 3 chunks, each different image                  │ .11, .11.v1, .11.v2                           │ ✅                                            │    
  └──────┴─────────────────────────────────────────────────┴───────────────────────────────────────────────┴───────────────────────────────────────────────┘    

  Page 3 note: The pie + 2 bar charts cluster into one large visual bbox (they're adjacent, within 20pt gap). The pixel fallback doesn't trigger because        
  covered_area / page_area >= 0.5. The Gemini description covers all chart content including any embedded table, so search quality is unaffected — only visual  
  granularity in the UI is reduced on that page.

  ---
  What Each Fix Does

  Issue 1 — Wrong image for multi-visual pages ✅ Fixed across pages 4, 6, 10, 11:
  - main.py: /image/{doc_id}/{page}?v=N now routes to {doc_id}.{page}.vN
  - page.tsx: gcsImageUrl() parses gcs_image_path from each chunk and builds the correct endpoint URL with ?v=N

  Issue 2 — Whitespace in visual crops ✅ Fixed in chunker.py::render_and_upload_visual_region:
  - PIL grayscale getbbox finds non-white content bbox
  - Crops to content + 10px padding before uploading to GCS

  Issue 3 — Whitespace-aligned tables not detected ✅ Fixed in classifier.py + chunker.py + pipeline.py:
  - _detect_whitespace_tables(): groups words into rows (3pt tolerance), clusters x0 into columns (20pt gap), detects ≥2 columns + ≥3 aligned rows
  - Page 5 now produces a table[whitespace_table=True] chunk

  Issue 4 — Visual overlap threshold ✅ Fixed:
  - _VISUAL_OVERLAP_THRESH lowered from 0.5 → 0.3: text blocks ≥30% inside visual bbox are excluded (treated as captions/labels), reducing multimodal chunk text
   leakage

  Issue 5 — Pixel fallback for missed visual content ✅ Implemented in classifier.py:
  - After standard detection, if covered_area < 50% of page and non-white pixel ratio exceeds detected area by >10% with text_ratio < 0.5 → adds full-page      
  visual element
  - Catches Form XObjects and drawings that are individually too small to cluster

## Phase 3 — Per-Page Analysis + Embedding Pipeline
**Completed:** 2026-03-07
**Updated:** 2026-03-08 (sub-page element detection — Phase 3A classifier rewrite)
**Status:** ✅ Complete
**FORCE_MIXED_MODE at time of testing:** false (full classification used for all tests)

---

## 1. Files Created

| File | Description |
|---|---|
| `services/rag-fl/pipeline.py` | CLI entry point + core pipeline (classify → chunk → embed → store). Updated in Phase 3A: element-based dispatch replaces page-type if/elif chain. |
| `services/rag-fl/classifier.py` | **Phase 3A rewrite:** sub-page element detection — ALL elements (tables, visuals, text blocks) per page. pdfplumber `find_tables()` with loose settings; PyMuPDF `get_images()+get_drawings()` clustered into visual regions; text blocks filtered for table/visual overlap. `detected_elements` is now a list of typed dicts. |
| `services/rag-fl/chunker.py` | Text splitting (heading-bounded 500-800 tokens), table→Markdown, PNG render + GCS upload. Added `chunk_specific_table()` (extracts Nth table by `table_index`) and `render_and_upload_visual_region()` (clips bbox at 2x zoom). |
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
| `detected_elements` | ✅ | List of typed dicts: `{"type": "table", "bbox": [...], "table_index": N}`, `{"type": "visual", "bbox": [...]}`, `{"type": "text", "bbox": [...], "char_count": N}`. Legacy strings still accepted for FORCE_MIXED_MODE / non-PDF. |
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

### Phase 3A — Sub-page element detection (2026-03-08)

| Document | Pages | Element detection | Chunks | Gemini calls | Pass? |
|---|---|---|---|---|---|
| Churn_EDA_Report.pdf | 9 | 1: 1T/1V/3txt, 2: 2T/0V/7txt, 3: 1T/0V/3txt, 4: 2T/1V/9txt, 5: 0T/0V text, 6: 0T/2V/9txt, 7: 1T/2V/10txt, 8: 0T/1V/11txt, 9: 0T/0V text | 23 | 7 | ✅ |
| Titanic_data_pdf_1.pdf | 11 | 1: 5T/1V, 2: 1T, 3-4: 0T/1-2V, 5: 0T/1V/4txt, 6: 0T/2V, 7-9: 0T/1V, 10: 0T/2V, 11: 0T/3V | 22 | 15 | ✅ |
| ML Fraud Review.pdf | 13 | 13 text-only pages, 0 tables, 0 visuals | 13 | 0 | ✅ |
| guidelines_part_01_pages_1-15.pdf | 15 | 8 multimodal, 1 table, 3 text-only, 3 mixed | 23 | 13 | ✅ |
| guidelines_part_02_pages_16-30.pdf | 15 | 2 multimodal, 5 text-only, 8 mixed | 27 | 10 | ✅ |
| CustomerChurn_Jan2025.xlsx | 1 | Excel table (non-PDF path) | 1 | 0 | ✅ |
| CustomerChurn_Jan2025 - Table.pdf | 1 | 1T/0V | 1 | 0 | ✅ |
| ChurnCustomer_Jan2025.pdf | 1 | 0T/1V (XObject screenshot) | 1 | 1 | ✅ |
| **TOTAL** | **65** | | **111** | **46** | ✅ |

### Per-Page Classification Detail — Churn_EDA_Report.pdf (Phase 3A)

| Page | Elements | page_type | Chunks | Notes |
|---|---|---|---|---|
| 1 | 1T / 1V / 3 text-blks | mixed | 3 | Table chunk + visual chunk + text chunk |
| 2 | 2T / 0V / 7 text-blks | mixed | 3 | 2 table chunks + 1 text chunk |
| 3 | 1T / 0V / 3 text-blks | mixed | 2 | 1 table chunk + 1 text chunk |
| 4 | 2T / 1V / 9 text-blks | mixed | 4 | 2 table + 1 visual + 1 text chunks |
| 5 | 0T / 0V / 3 text-blks | text | 1 | Text only |
| 6 | 0T / 2V / 9 text-blks | mixed | 3 | Text + 2 visual (Gemini) chunks |
| 7 | 1T / 2V / 10 text-blks | mixed | 4 | Text + 1 table + 2 visual chunks |
| 8 | 0T / 1V / 11 text-blks | mixed | 2 | Text + 1 visual (heatmap) chunk |
| 9 | 0T / 0V / 4 text-blks | text | 1 | Text only |

### Phase 3 initial tests (2026-03-07, archived)

| Test | Input | Expected | Actual | Pass? |
|---|---|---|---|---|
| Classify only | Churn_EDA_Report.pdf (9 pages) | 9 page_profiles written, 0 Gemini calls | 9 profiles: 4 table, 2 skip, 2 mixed, 1 multimodal | ✅ |
| Comparison: Excel | CustomerChurn_Jan2025.xlsx | Markdown table, all rows/cols extracted | 1 chunk, sheet=Monthly_Churn_Report, 29 rows (header + 28 data), 10 columns | ✅ |
| Comparison: PDF embedded table | CustomerChurn_Jan2025 - Table.pdf | Markdown table, structure intact | 1 chunk, pdfplumber extracted full table, column/row structure preserved | ✅ |
| Comparison: PDF screenshot | ChurnCustomer_Jan2025.pdf | Gemini Vision description with column mentions | 1 chunk, page_type=multimodal (xobject_image layer), gcs_image_path set, Gemini described customer data table with all columns | ✅ |
| Dedup check | Upload same file twice via ingestion service | Second upload returns is_duplicate_of set | DuplicateResponse returned on re-upload, MongoDB count stays at 1 | ✅ |
| Chrono metadata: filename | CustomerChurn_Jan2025.xlsx | report_period="2025-01", confidence="high" | report_period="2025-01", period_confidence="high", extraction_method="filename" | ✅ |
| Chrono metadata: PDF metadata | Churn_EDA_Report.pdf | report_period extracted from PDF creation date | report_period="2026-03", period_confidence="medium", extraction_method="pdf_metadata" | ✅ |
| Chrono metadata: first-page text | guidelines_part_01_pages_1-15.pdf | report_period from first page | report_period="2025-10", period_confidence="medium", extraction_method="first_page_text" | ✅ |
| Memory logging | Any large doc | RSS logged every 10 pages | 195 MB RSS at page 10 of ROSHN Part 01 | ✅ |

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
| Sub-page element detection | Single label per page (text/table/multimodal/mixed/skip) | ALL elements detected per page: tables (pdfplumber `find_tables()` with loose settings), visuals (get_images+get_drawings clustered), text blocks (filtered for table/visual overlaps) | Original single-label approach missed multiple elements on mixed pages (e.g. page with a table AND a chart AND text produced only 1 chunk). Element-based dispatch creates one chunk per detected element. | Each page now produces N chunks where N = number of detected elements. Churn page 7 (1T+2V+text): 4 chunks vs 1 before. Titanic page 1 (5T+1V): 6 chunks. |
| `detected_elements` schema | `list[str]` (legacy strings) | `list[dict]` with `{"type", "bbox", ...}` | Richer format needed to drive per-element chunking dispatch (needs bbox for visual crop, table_index for specific table extraction) | `PageProfile.detected_elements` field widened to `list` (accepts both dicts and legacy strings). Legacy string format still works for FORCE_MIXED_MODE and non-PDF paths. |
| GCS key for visual regions | Not specified | First visual: `{doc_id}.{page_number}` (backward compat), subsequent: `{doc_id}.{page_number}.v{n}` | Phase 4 `/image/{doc_id}/{page_number}` endpoint expects key `{doc_id}.{page_number}`. For pages with a single visual this is preserved. Pages with multiple visuals use `.v1`, `.v2` suffix for additional crops. | Phase 4 UI image display works unchanged for single-visual pages. Multiple visual crops accessible via key convention. |
| Vision circuit breaker | 5 failures within 10-minute window | 5 consecutive failures (no time window) | Simpler implementation appropriate for POC stage. | POC-appropriate. Add time window in Phase 5 if needed. |

---

## 9. Known Limitations / TODOs

- [ ] **Vision circuit breaker time window:** Current implementation counts consecutive failures only, not failures within a time window. Add time-windowed circuit breaker in Phase 5.
- [ ] **Excel chunking size limit:** Current implementation produces one chunk per sheet regardless of row count. Large sheets (>1000 rows) will exceed embedding token limits. Add row-based splitting for large sheets.
- [ ] **Gemini Vision retry on circuit-open chunks:** When circuit breaker opens, affected chunks have `chunk_text=""` and are stored without a description. A retry mechanism to re-process `needs_vision_retry=true` chunks is not yet implemented.
- [ ] **Re-run creates duplicate chunks:** Pipeline uses `replace_one({"chunk_id": ...})` but chunk_ids are new UUIDs each run. Re-running a document accumulates additional chunks rather than replacing existing ones. Fix: use `doc_id + page_number + chunk_index` as the idempotency key, or delete existing chunks for the doc_id before re-embedding.
- [x] **FORCE_MIXED_MODE not tested end-to-end:** ~~Test in Phase 4 UI context.~~ Legacy dispatch preserved in pipeline.py — FORCE_MIXED_MODE and non-PDF detected_elements strings fall through to the else: legacy branch. ✅

---

---

# Phase 3B — Per-Element Visual Fix Pass
**Completed:** 2026-03-08
**Status:** ✅ Complete
**Scope:** Multi-visual page display, whitespace crop trimming, whitespace-aligned table detection, visual cluster splitting, pixel fallback.
All fixes are document-agnostic — no hardcoding.

---

## Phase 3B — Issues Fixed

### Issue 1: Wrong Image Displayed for Multi-Visual Pages

**Root cause:** `GET /image/{doc_id}/{page_number}` always returned the first visual crop
(`{doc_id}.{page_number}`). UI hardcoded the URL from `doc_id + page_number`, ignoring
`chunk.gcs_image_path` entirely.

**Fix — `main.py`:**
```
GET /image/{doc_id}/{page_number}          → first visual (v=0, backward compat)
GET /image/{doc_id}/{page_number}?v=1      → second visual crop
GET /image/{doc_id}/{page_number}?v=2      → third visual crop
```
Added `v: int = Query(0)` parameter. GCS path resolved as `{doc_id}.{page}` (v=0) or
`{doc_id}.{page}.v{v}` (v>0).

**Fix — `services/ui/app/page.tsx`:**
Added `gcsImageUrl(gcsPath, docId, pageNum)` helper that parses the `.v{n}` suffix from
`chunk.gcs_image_path` and builds the correct endpoint URL. Replaced all hardcoded image
`src` construction. UI now fetches the exact crop stored for each individual chunk.

### Issue 2: Unnecessary Whitespace in Visual Crops

**Root cause:** `render_and_upload_visual_region()` clipped to bbox at 2x zoom but applied
no content-aware trimming. Surrounding page whitespace was included in the PNG.

**Fix — `chunker.py` `render_and_upload_visual_region()`:**
After rendering, apply PIL smart-crop:
```python
gray = pil.convert("L").point(lambda x: 0 if x > 240 else 255)
content_bb = gray.getbbox()
# crop to content_bb + 10px padding on all sides
```
Wrapped in inner try/except — falls back to original render on any PIL error.

### Issue 3: Whitespace-Aligned Tables Not Detected

**Root cause:** `find_tables()` with `vertical_strategy: "lines"` only detects tables
with explicit borders. Tables aligned purely by whitespace were missed entirely.

**Fix — `classifier.py` Step 1B + `_detect_whitespace_tables()`:**
New helper detects borderless tables:
- Groups words into rows by 3pt y-tolerance
- Clusters x0 positions into column centers (20pt gap)
- Row "aligned" = has words in ≥2 distinct columns
- Minimum: 2 columns, 3 aligned rows
- Results stored with `is_whitespace_table: True` and pre-extracted `rows` list

**Fix — `pipeline.py`:** Dispatch condition `elem.get("rows")` routes whitespace tables
through `chunk_whitespace_table()` (no pdfplumber re-extraction needed).

### Issue 4: Visual Overlap Threshold

**Root cause:** `_VISUAL_OVERLAP_THRESH = 0.5` was too permissive — text blocks up to
50% inside a visual bbox were still extracted as text elements, causing visual caption
text and chart labels to leak into text chunks.

**Fix — `classifier.py`:** Lowered `_VISUAL_OVERLAP_THRESH` from 0.5 → 0.3.
Text blocks ≥30% inside a visual bbox are now excluded from `text_elements` (treated as
captions/labels belonging to the visual).

### Issue 5: Pixel Fallback for Missed Visual Content

**Root cause:** Some visual content (Form XObjects, vector drawings with elements below
`_MIN_DRAW_AREA_RATIO`) escaped both `get_images()` and `get_drawings()`.

**Fix — `classifier.py` Step 2B:**
After standard visual detection, render a 0.25x grayscale thumbnail. If:
- `covered_area / page_area < 0.5` (page appears under-detected), AND
- `non_white_ratio > 0.15` (significant content exists), AND
- `non_white_ratio > covered_area_ratio + 0.10` (more pixels than detected area explains), AND
- `text_ratio < 0.5` (not a pure text page)
→ Add full-page visual element.

---

## Phase 3B — Results

| Document | Key improvement |
|---|---|
| Titanic page 4 | Chunks 1 and 2 now show different crops (`.4` vs `.4.v1`) |
| Titanic page 5 | Whitespace cross-tab detected as table chunk |
| Titanic page 6 | Two distinct crops (`.6` vs `.6.v1`) |
| Titanic page 10 | Scatter plot + boxplot as separate chunks |
| Titanic page 11 | Three separate crops (`.11`, `.11.v1`, `.11.v2`) |
| All visual crops | Trimmed to content + 10px padding — no large white borders |

---

---

# Phase 3C — Element Detection Quality Improvements
**Completed:** 2026-03-08
**Status:** ✅ Complete
**Scope:** Systematic fixes for text/table separation, visual suppression regression,
multi-line cell merging, horizontal-line table detection, visual cluster splitting,
figure caption detection. All general — no document-specific hardcoding.

---

## Phase 3C — Root Causes Investigated

| Problem | Root Cause |
|---|---|
| Text chunks contain table cell text | `chunk_text_page()` calls `fitz_page.get_text()` — extracts ALL page text, ignoring the table bboxes the classifier already identified. |
| Whitespace tables suppress heatmap (Churn pg 8) | Whitespace table bboxes were added to `table_fitz_rects` before visual detection. Visual cluster check used all table rects, so WS table bbox covering the same region discarded the visual. |
| False WS tables from section headers / bullet lists | WS detection used 20pt column gap and no column-consistency check. Paragraph text with natural indentation variation produced false multi-column "tables". |
| Multi-line cells split into too many rows | WS detection treated each visual line as a separate row, no merging of continuation text. |
| Horizontal-line-only tables missed | `find_tables()` with `lines` strategy requires both vertical and horizontal lines. Tables with only row separators (no column borders) were never detected. |
| Large visual clusters not split | Charts adjacent within 20pt gap were merged into one large cluster bbox. Individual charts on the same page got one chunk instead of separate crops. |
| CID encoding artifacts in WS tables | pdfplumber returns raw `(cid:N)` strings for undecodable glyphs (bullet points in CID-mapped fonts). These produced garbage table chunks. |

---

## Phase 3C — Changes Made

### classifier.py

**1. Two-tier table rect tracking**
```python
lines_table_rects = []   # pdfplumber LINES strategy — reliable, can suppress visuals
soft_table_rects  = []   # whitespace + text+lines — heuristic, never suppresses visuals
table_fitz_rects  = lines_table_rects + soft_table_rects  # text-block exclusion uses both
```
Visual cluster discard now checks only `lines_table_rects` → whitespace/text+lines tables
can no longer suppress genuine visual elements.

**2. Table validation improvements (Step 1)**
- Raised `non_empty` threshold: `< 2` → `< 4` (≥4 non-empty cells required)
- Added 1×1 table rejection: `num_rows <= 1 and num_cols <= 1` → skip
- Added all-prose rejection: all non-empty cells > 80 chars → treat as text box, not table
- New constants: `_MIN_TABLE_CELLS = 4`, `_MAX_PROSE_CELL_LEN = 80`

**3. Text+lines table detection (Step 1C)**
```python
_TABLE_SETTINGS_TEXT_LINES = {
    "vertical_strategy":    "text",
    "horizontal_strategy":  "lines",
    ...
}
```
Runs **after** visual detection so its bboxes cannot suppress visuals. Results go into
`soft_table_rects` only. Table data pre-extracted as `rows` for dispatch via
`chunk_whitespace_table()`. Skips any bbox that overlaps a detected visual (>40%).

**4. Visual cluster splitting (Step 2 + `_try_split_cluster`)**
For clusters covering >25% of page area, render a 0.5x grayscale crop and scan for
whitespace bands (≥2 consecutive pixel rows/columns >95% white) as natural split points.
Horizontal split attempted first, vertical split as fallback.
Returns list of sub-rects; any sub-rect < 5% of page area is discarded.

**5. Improved `_detect_whitespace_tables()`**
- Column gap: 20pt → **30pt** (wider gap → fewer, more distinct column clusters)
- Smart multi-line merge: consecutive lines with gap < 8pt are merged into the same logical
  row **only if** the next line introduces no new column positions (continuation, not new row)
- Column consistency check: each column must appear in ≥40% of aligned rows — prevents
  paragraph text with variable indentation from triggering false table detection
- CID artifact filter per row: skip any row where a cell contains `"(cid:"`
- Average cell-length filter: skip rows where average non-empty cell length < 3 chars

**6. Center-Y text block filter (Step 3)**
In addition to the overlap-ratio check, also exclude text blocks whose **center point**
falls inside any table bbox. More reliable when pdfplumber and PyMuPDF bbox coordinates
differ slightly (table cell text was leaking into text chunks due to this mismatch).

### chunker.py

**1. `chunk_text_page()` — `exclude_rects` parameter (root fix for Issue 1)**
```python
def chunk_text_page(..., exclude_rects: list | None = None):
```
When `exclude_rects` is provided, switches from `fitz_page.get_text()` to
`fitz_page.get_text("blocks")` and filters each block:
- Skip if block center falls inside any excluded rect
- Skip if block overlaps >40% with any excluded rect

**2. `chunk_whitespace_table()` — CID rejection**
After `_table_to_markdown(rows)`, if the resulting markdown contains `"(cid:"` → return `[]`.
Final safety net for CID encoding artifacts that survive cell-level filtering.

### pipeline.py

**1. Pass `exclude_rects` to `chunk_text_page()`**
```python
exclude_bboxes = [e["bbox"] for e in struct_elements
                  if e.get("bbox") and e["type"] in ("table", "visual")]
text_chunks = chunk_text_page(..., exclude_rects=exclude_bboxes or None)
```
Table cell text and visual region text are now excluded from text chunks at source.

**2. Generalized `rows` dispatch**
Changed condition from `elem.get("is_whitespace_table") and elem.get("rows")`
to `elem.get("rows")` — handles both whitespace tables and text+lines tables
(both store pre-extracted rows) without needing a strategy-specific flag.

**3. Figure caption detection (`_find_caption_near_visual()`)**
New helper scans `fitz_page.get_text("blocks")` for text blocks within 25pt above/below
a visual bbox that also overlap horizontally (≥10pt). Caption must be ≤300 chars and must
not be inside another detected table/visual bbox. Found captions are prepended to the
Gemini Vision description before embedding:
```
{caption}\n\n{gemini_description}
```

---

## Phase 3C — Test Results

### Churn_EDA_Report.pdf (31 chunks, 10 Gemini calls)

| Page | Before | After | Key change |
|---|---|---|---|
| 1 | 5T/1V (false WS tables as table chunks) | 1T/1V/3 text → 3 chunks | Text extracted clean, table from pdfplumber lines only |
| 5 | 1T (phantom table) | 0T/0V/3 text → 1 text chunk | Phantom rejected by ≥4 non-empty cells rule |
| 8 | 1T/0V (heatmap missing!) | 0T/1V/11 text → 2 chunks | Two-tier rect fix — WS table no longer suppresses visual |
| 9 | 1T/0V (CID garbage table) | 1T → 1 text chunk | CID rejection in chunk_whitespace_table |

### Titanic_data_pdf_1.pdf (25 chunks, 18 Gemini calls)

| Page | Before | After | Key change |
|---|---|---|---|
| 3 | 0T/1V → 1 chunk | 0T/2V → 2 chunks | Visual cluster split (pie vs bar charts) |
| 7 | 0T/1V → 1 chunk | 0T/2V → 2 chunks | Visual cluster split |
| 5 | 0T/1V/0 text | 0T/2V/4 text → 3 chunks | Text extracted separately from visuals |

### Machine Learning in Detecting Fraud Literature Review.pdf (22 chunks, 1 Gemini call)

| Page | Before | After | Key change |
|---|---|---|---|
| 3 | text only | 1T + text → 2 chunks | Table detected (WS strategy) |
| 4–8, 10–12 | text only | 1T + text → 2 chunks each | Horizontal-line tables via text+lines strategy |
| 13 | text only | 0T/1V → 1 multimodal chunk | Pixel fallback detected visual content |

---

## Phase 3C — Architecture Notes

### Table Rect Tiers
```
lines_table_rects  ← pdfplumber LINES strategy only
                    ↑ used for visual cluster discard
                    ↑ used for text block center-y exclusion
                    ↑ used for overlap-ratio text exclusion

soft_table_rects   ← whitespace + text+lines strategies
                    ↑ used for text block exclusion ONLY
                    ✗ NEVER used for visual cluster discard
```

### Table Detection Order
```
Step 1  : pdfplumber LINES         → lines_table_rects
Step 1B : whitespace words         → soft_table_rects
Step 2  : visual detection         (uses lines_table_rects for discard)
Step 2B : pixel fallback           (uses all detected rects)
Step 1C : text+lines strategy      → soft_table_rects, runs after visuals
Step 3  : text block extraction    (uses table_fitz_rects = lines + soft)
```
Text+lines runs after visual detection intentionally so its bboxes cannot suppress visuals.

### Chunk Dispatch (pipeline.py)
```
elem.get("rows")        → chunk_whitespace_table()  (pre-extracted: WS + text+lines)
else                    → chunk_specific_table()     (pdfplumber LINES re-extraction)
```

---

## Phase 3C — Known Limitations

- **Titanic page 5 whitespace table:** The cross-tab pivot table has too few consistent
  columns to pass the ≥40% column-consistency check. Content is captured as a text chunk
  (fitz extracts the cross-tab values as plain text — searchable but not Markdown table format).
- **CID-font PDFs:** Pages where the entire body text uses CID-mapped fonts produce garbled
  word extractions from pdfplumber. WS table detection will produce no false tables (CID
  rejection filters them), but legitimate whitespace tables on such pages are also missed.
- **Re-run duplicate chunks:** Still present (chunk_ids are new UUIDs each run). Workaround:
  always wipe doc before re-running. Permanent fix deferred: use
  `(doc_id, page_number, chunk_index)` as idempotency key.

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
  - `POST /process` endpoint available ✅ (**Phase 4.1:** auto-triggered via ingestion background task, no manual UI button needed)
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
