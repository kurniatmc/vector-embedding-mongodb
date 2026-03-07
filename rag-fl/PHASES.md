# RAG-FL Phase Roadmap
> Track implementation progress. Update status after each phase completes.
> **Last updated:** Post "Sync on Embedding" meeting with Harsh, Abhinav, and team.

---

## ⚠️ PIVOT NOTE

**Harsh's direction (from meeting):**
> "No batching. We are not talking about productization. We are talking about explainability.
> If you give a PDF, what are the embeddings? If I go to page 4, does it make sense?
> We need a UI — pick a file and explain what exactly is held there."

**Abhinav's suggestion (adopted):**
> "Maybe we can just use mixed version for PDF pages — treat all as mixed type."
→ Implemented as `FORCE_MIXED_MODE` env var (true=Abhinav mode, false=full classification).

**Schema alignment note (Harsh):**
> "The schema of MongoDB — what is going in — has to be aligned with everything first."
→ See ARCHITECTURE.md Canonical Chunk Schema. Finalized. Do not deviate.

**What changed:**
- Phase 3 (File Ledger/Batch) → DEFERRED — already in Harsh's production pipeline
- New Phase 3 = Per-Page Analysis + Embedding (the rag-fl core)
- New Phase 4 = Next.js Observability UI (Harsh's explicit request)
- `documents{}` schema extended with `content_hash` + chronological metadata fields
- `FORCE_MIXED_MODE` env var added for Abhinav's mixed-default suggestion

**What did NOT change:**
- Phase 1 ✅ and Phase 2 ✅ — valid and complete, do not re-implement
- All BMP diagram decisions remain valid
- vector_search.py, gcs_client.py, mongo_client.py from Phase 1-2 stay as-is

---

## Phase Status

| Phase | Name | Status | Summary Doc |
|---|---|---|---|
| 0 | Standards & Contracts | ✅ Done | ARCHITECTURE.md |
| 1 | Docker Infrastructure | ✅ Done | docs/phase_summaries/phase_1_summary.md |
| 2 | Format Registry & Ingestion | ✅ Done | docs/phase_summaries/phase_2_summary.md |
| 3 | Per-Page Analysis + Embedding Pipeline | ✅ Done | docs/phase_summaries/phase_3_summary.md |
| 4 | Next.js Observability UI | ⬜ Not started | — |
| 5 | Citation Engine & Provenance API | ⬜ Not started | — |
| 6 | Search & Retrieval API | ⬜ Not started | — |
| 7 | Production / Cloud Run Migration | ⬜ Not started | — |
| — | ~~File Ledger & Batch Orchestration~~ | ❌ Deferred | Exists in Harsh's pipeline |

Legend: ✅ Done | 🔄 In Progress | ⬜ Not Started | ❌ Deferred

---

## Phase 0 — Standards & Contracts
**Status:** ✅ Complete

- [x] Canonical Chunk Schema (all fields aligned with Harsh)
- [x] Format Registry Interface
- [x] Document Provenance Model — extended with content_hash + chronological fields
- [x] Local-Production Parity Contract
- [x] File System Contracts (GCS naming: {doc_id}.{page_number})
- [x] Vector search wrapper (local cosine ↔ Atlas $vectorSearch)
- [x] Asymmetric embedding task_type (RETRIEVAL_DOCUMENT vs RETRIEVAL_QUERY)

---

## Phase 1 — Docker Infrastructure
**Status:** ✅ Complete
**Summary:** docs/phase_summaries/phase_1_summary.md

- [x] docker-compose.yml: MongoDB 7 (rs0), Redis, fake-gcs, Gotenberg, Mongo Express
- [x] MongoDB init: 5 collections + 768-dim cosine vector index
- [x] .env.example, Makefile
- [x] shared/utils/vector_search.py
- [x] GCS bucket rag-fl-documents created
- [x] All 5 containers healthy

**No changes needed from Harsh/Abhinav feedback.**

---

## Phase 2 — Format Registry & Ingestion Service
**Status:** ✅ Complete
**Summary:** docs/phase_summaries/phase_2_summary.md

- [x] BaseProcessor + 7 format processors (PDF, PPTX, DOCX, Excel, YAML, JPEG, PNG)
- [x] FormatRegistry (MIME → Processor)
- [x] Folder watcher /input (dev mode)
- [x] OneDrive webhook stub
- [x] ?dry_run=true on all endpoints
- [x] shared/schemas/ (chunk.py, document.py, page_profile.py)
- [x] shared/utils/gcs_client.py, mongo_client.py
- [x] Tested with all 5 sample PDFs

**Schema update required:** Add `content_hash`, `is_duplicate_of`, `report_series`,
`report_period`, `report_period_start`, `report_period_end`, `report_frequency`,
`period_confidence`, `extraction_method`, `upload_timestamp`, `uploaded_by`
to documents{} on ingest. See ARCHITECTURE.md Document Schema section.

---

## Phase 3 — Per-Page Analysis + Embedding Pipeline
**Status:** ⬜ Not started — START HERE
**Goal:** The rag-fl core from BMP diagram. file → classify → chunk → embed → store.

This is what Harsh wants to inspect at the next 30-minute sync.

### 3A — Per-Page Classification (zero API cost)

**FORCE_MIXED_MODE=true:** skip classification, treat all PDF pages as "mixed"
(Abhinav's suggestion — faster dev, higher Gemini cost, good for initial testing)

**FORCE_MIXED_MODE=false (default):** run full classification:

- [ ] Layer 1: PyMuPDF — compute text_ratio, image_ratio per page
- [ ] Layer 2: Pillow — visual analysis for ambiguous pages (color_variance, edge_density)
- [ ] pdfplumber table override — ≥1 table found → page_type = "table"
- [ ] Non-PDF handler: Excel sheet→table, YAML→structured_text, JPEG/PNG→multimodal
- [ ] Write every page to MongoDB page_profiles{} with all fields
- [ ] Console classification report per page after analysis

### 3B — Chunking + Embedding (uses Google APIs)

- [ ] Pre-flight dry_run: count Gemini calls, warn if > DRY_RUN_THRESHOLD
- [ ] "text" pages: PyMuPDF extract → heading-boundary split → 500-800 tokens → embed (RETRIEVAL_DOCUMENT)
- [ ] "table" pages: pdfplumber extract → Markdown format → embed (RETRIEVAL_DOCUMENT)
- [ ] "multimodal" pages:
  - [ ] Render PNG at zoom 2x (PyMuPDF)
  - [ ] Save to /output/flat-images/{doc_id}_page_{n}.png
  - [ ] Upload to fake-gcs at {doc_id}.{page_number}
  - [ ] Gemini 1.5 Flash: describe page (content, numbers/labels, relationships)
  - [ ] Embed description (RETRIEVAL_DOCUMENT)
  - [ ] Store with gcs_image_path populated
- [ ] "mixed" pages: text chunk (index 0) + full-page image chunk (index 1), same page_number
- [ ] "skip" pages: log only, no doc_embeddings record
- [ ] Memory streaming: process one page, del objects, next page
- [ ] Memory log every 10 pages

### 3C — Inspection Report (Harsh: "does page 4 embedding make sense?")

After processing, print per-page report:
```
=== EMBEDDING INSPECTION REPORT ===
Document: Churn_EDA_Report.pdf | 9 pages | 18 chunks
Page  1 | text        | 2 chunks | "This report analyzes customer churn..."
Page  4 | mixed       | 2 chunks | text: "KPI Summary..." | visual: Gemini: "Dashboard with 4 metric cards..."
Page  8 | multimodal  | 1 chunk  | Gemini: "Pearson correlation heatmap showing..."
Page  7 | table       | 1 chunk  | "| Churn | Internet Service |..."
```

### 3D — Comparison Test (Harsh's explicit request)

Run against all 3 comparison files, side by side:
```
Excel native    → ExcelProcessor → pdfplumber → Markdown → embed
PDF embedded    → PDFProcessor → pdfplumber → Markdown → embed
PDF screenshot  → PDFProcessor → multimodal → Gemini Vision → embed description
```
Compare: column count, row count, data accuracy, embedding similarity score between Excel and PDF versions.
Document deviations in phase_3_summary.md.

### Test Sequence (cheapest first — protect API key)
1. `--classify-only` on Churn_EDA_Report.pdf → 0 API calls, verify page_profiles
2. Full pipeline on Churn_EDA_Report.pdf → ~5 Gemini calls
3. Full pipeline on guidelines_part_01_pages_1-15.pdf → ~8 Gemini calls
4. Comparison test: Excel vs PDF-embedded vs PDF-screenshot
5. All 5 sample docs

### Validation
```bash
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.countDocuments({})"
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({chunk_type: 'multimodal'})"
# Must have: gcs_image_path populated, chunk_text = Gemini description
docker compose exec mongo mongosh ragfl --eval "db.page_profiles.countDocuments({})"
# Must equal total pages across all processed docs
docker compose exec mongo mongosh ragfl --eval "db.documents.findOne({}, {content_hash:1, report_period:1, period_confidence:1})"
# Must have content_hash. report_period may be null if not detectable.
```

---

## Phase 4 — Next.js Observability UI
**Status:** ⬜ Not started — After Phase 3
**Goal:** Harsh's explicit request — "pick a file and explain what exactly is held there"
**Reference:** BMP diagram (bottom right): "track list of files and exploration of embedding: contexts, chunks, charts or tables"

This is a RESEARCH/DEMO UI, not production. Built for Harsh to inspect embeddings at 30-min syncs.

### Deliverables

**Left panel — File List**
- [ ] GET /documents → list all docs (filename, format, pages, chunk count, status)
- [ ] Click to select a document

**Center panel — Page Explorer**
- [ ] GET /document/{doc_id}/pages → per-page breakdown
- [ ] Color-coded badges: text=blue, table=green, multimodal=purple, mixed=orange, skip=gray
- [ ] Click page → expand chunk details:
  - text: show chunk_text
  - table: render Markdown table
  - multimodal: show rendered PNG image + Gemini description below image
- [ ] Show embedding dimension count (768) as confirmation it is stored

**Right panel — Search**
- [ ] Text input "Ask anything about this document"
- [ ] POST /search/within/{doc_id} → top 5 results
- [ ] Show: score | page_number | chunk_type | text snippet
- [ ] Citation label per result: "Page N, Section title"
- [ ] Click result → highlight page in center panel

**Top bar**
- [ ] Upload button → POST /ingestion/ingest
- [ ] Processing status indicator
- [ ] "Process" button → trigger Phase 3 pipeline for uploaded doc

**New API endpoints to add to rag-fl FastAPI service:**
```
GET /documents                           → list all docs
GET /document/{doc_id}/pages             → per-page profile
GET /document/{doc_id}/chunks/{page_n}  → chunks for one page
GET /document/{doc_id}/status            → processing progress
```

**Stack:** Next.js + Tailwind CSS, Docker port 3001, added to docker-compose.yml

---

## Phase 5 — Citation Engine & Provenance API
**Status:** ⬜ Not started — After Phase 4 UI is running
**Goal:** Harsh requirement #1 — exact page citations like Perplexity/Gemini/ChatGPT

Citation format by source type (see ARCHITECTURE.md Citation Format section).
Adjacent pages ±1 from same doc → merge into one citation.
Deep links: PDF anchor (#page=N) | multimodal = signed GCS URL (1hr TTL).

### Deliverables
- [ ] POST /citations/generate {chunk_ids} → [{label, page_number, doc_id, deep_link, chunk_type}]
- [ ] GET /citations/preview/{doc_id}/{page} → tooltip snippet
- [ ] GET /provenance/document/{doc_id} → full page breakdown
- [ ] GET /provenance/chunk/{chunk_id} → full provenance trail
- [ ] Citation cache (MongoDB citation_cache{}, TTL 1hr)

### Validation
```
Churn EDA page 7 chunks → "Churn EDA Report, Page 7, Table 4: Churn by Internet Service"
ROSHN Part 01 multimodal page → citation includes signed GCS URL + Gemini description snippet
Excel chunk → "Churn_Jan2025.xlsx, Sheet: Monthly_Churn_Report, Rows 5–10"
```

---

## Phase 6 — Search & Retrieval API
**Status:** ⬜ Not started — After Citation Engine

**CRITICAL:** query embedding MUST use task_type="RETRIEVAL_QUERY" (different from storage).
Always use shared/utils/vector_search.py — never raw MongoDB query.

### Deliverables
- [ ] POST /search {query, top_k=5, filters={doc_ids, format}, include_multimodal=true}
- [ ] POST /search/within/{doc_id} {query, top_k=5}
- [ ] GET /document/{doc_id}/summary
- [ ] Query cache (Redis, 1hr TTL, key=sha256(query))
- [ ] Target: <500ms p95

### Response shape (Next.js UI compatible)
```json
{
  "answer_chunks": [
    {"chunk_id": "...", "chunk_text": "...", "chunk_type": "text",
     "score": 0.94, "page_number": 13, "doc_id": "..."}
  ],
  "citations": [
    {"label": "ROSHN Part 01, Page 13, Section 2.1",
     "page_number": 13, "doc_id": "...", "deep_link": "...", "chunk_type": "text"}
  ],
  "query_metadata": {"docs_searched": 5, "response_time_ms": 312}
}
```

### End-to-End Validation
```
"what is FAR for medium density development?"
  → citation: ROSHN Guidelines Part 01, Page ~13, Section 2.1

"what is churn rate for fiber optic customers?"
  → citation: Churn EDA Report, Page 7, Table 4

"what ML approaches detect fraud?"
  → citation: Fraud Literature Review, relevant page

"show me churn data from January 2025"
  → citation: Churn_Jan2025.xlsx, filter by report_period="2025-01"
```

---

## Phase 7 — Production / Cloud Run Migration
**Status:** ⬜ Not started

- [ ] Push all Docker images to Artifact Registry
- [ ] Cloud Run service configs (ingestion, rag-fl, ui, citation-engine, search-api)
- [ ] Switch MONGODB_URI → Atlas connection string
- [ ] Create Atlas $vectorSearch index (embedding_index, 768 dim, cosine)
- [ ] Switch GCS_ENDPOINT → real GCS
- [ ] Switch credentials → Service Account
- [ ] Set ENVIRONMENT=production, FORCE_MIXED_MODE=false
- [ ] GCS lifecycle: archive images > 90 days
- [ ] Cloud Monitoring alerts (pipeline stopped, Gemini error rate)
- [ ] Structured JSON logging (stdout → Cloud Logging)

---

## Inter-Phase Dependencies (Revised)

```
Phase 0 (Contracts — schema aligned with Harsh)
    └── Phase 1 ✅ (Infrastructure)
            └── Phase 2 ✅ (Format Registry — 7 processors, dedup, chrono metadata)
                    └── Phase 3 (Per-page + Embedding) ← NOW
                            ├── Phase 4 (Observability UI) ← after Phase 3
                            └── Phase 5 (Citation Engine)
                                    └── Phase 6 (Search API)
                                            └── Phase 7 (Production)

DEFERRED (Harsh's existing pipeline handles this):
    File Ledger & Batch Orchestration
```
