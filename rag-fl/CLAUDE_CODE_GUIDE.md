# Claude Code — End-to-End Implementation Guide
> How to use Claude Code to build rag-fl, phase by phase.
> **Updated:** Post "Sync on Embedding" meeting — schema aligned, chrono metadata added,
> FORCE_MIXED_MODE added, comparison test added.

---

## Prerequisites Check

```powershell
node --version       # Need v18+. You have v24.11.1 ✅
docker --version     # Docker Desktop running ✅
code --version       # VSCode ✅
claude --version     # Claude Code CLI
```

---

## One-Time Setup (Already Done — For Reference)

```
E:\Work\TMC - Roshn\Work\Embedding Projects POC\
├── code\rag-fl\                ← Git repo (project root)
│   ├── ARCHITECTURE.md        ← Always read first
│   ├── PHASES.md
│   ├── CLAUDE_CODE_GUIDE.md
│   ├── PHASE_SUMMARY_TEMPLATE.md
│   ├── .env
│   ├── docker-compose.yml     ✅ Phase 1
│   ├── Makefile               ✅ Phase 1
│   ├── infra/mongo-init/      ✅ Phase 1
│   ├── shared/utils/          ✅ vector_search.py, gcs_client.py, mongo_client.py
│   ├── shared/schemas/        ✅ chunk.py, document.py, page_profile.py
│   ├── services/ingestion/    ✅ Phase 2
│   ├── tests/sample-docs/     ✅ 5 PDFs + comparison Excel/PDF test set
│   └── docs/phase_summaries/  ✅ phase_1_summary.md, phase_2_summary.md
├── input\
└── output\
    ├── embedding-db\
    └── flat-images\
```

---

## Session Start Protocol — Paste This EVERY Session

```
Read ARCHITECTURE.md and PHASES.md completely before writing any code.
Then read docs/phase_summaries/phase_6_summary.md for latest context.

Tell me:
1. Which phase are we implementing (check PHASES.md status + pivot note)
2. What was completed last session (read latest docs/phase_summaries/)
3. Any open blockers

Do not write any code until you confirm you have read all three files.
Note: FORCE_MIXED_MODE env var controls classification behavior — check .env before starting.
```

---

## Current Status

✅ Phase 1 — Docker Infrastructure
✅ Phase 2 — Format Registry & Ingestion (5 docs tested)
✅ Phase 3 — Per-Page Analysis + Embedding (130 embeddings, 99 profiles, 11 docs)
✅ Phase 4 — Next.js Observability UI (http://localhost:3001)
✅ Phase 5 — Citation Engine
✅ Phase 6 — Search & Retrieval API
❌ File Ledger / Batch — DEFERRED

---

## Phase 3 Prompt — Per-Page Analysis + Embedding

**Before starting:**
```cmd
docker compose ps
# All 5 containers must show Up (healthy)
```

**Send to Claude Code:**

```
Read ARCHITECTURE.md, PHASES.md, docs/phase_summaries/phase_2_summary.md fully.
Note the PIVOT NOTE at top of PHASES.md and the Schema Alignment requirement from Harsh.

Phase 3 goal: services/rag-fl/ — the core embedding pipeline from our BMP diagram.

=== SCHEMA REQUIREMENT (Harsh: most important point) ===

All chunks stored to MongoDB doc_embeddings{} MUST match the Canonical Chunk Schema
in ARCHITECTURE.md exactly. No missing fields. Align before writing any code.

All documents stored to MongoDB documents{} MUST include the new fields from ARCHITECTURE.md
Document Schema: content_hash, is_duplicate_of, report_series, report_period,
report_period_start, report_period_end, report_frequency, period_confidence,
extraction_method, upload_timestamp, uploaded_by.

These fields are also required in shared/schemas/document.py Pydantic model.
Update Phase 2 shared/schemas/ before implementing Phase 3.

=== PART A: PER-PAGE CLASSIFICATION (zero API cost) ===

Read FORCE_MIXED_MODE from .env:

If FORCE_MIXED_MODE=true:
  - Skip all classification
  - Treat every PDF page as "mixed"
  - Log: "FORCE_MIXED_MODE=true — skipping classification, all pages → mixed"
  - Still write page_profiles with page_type="mixed"

If FORCE_MIXED_MODE=false (default):
  For each page in the PDF run three layers:

  Layer 1 — PyMuPDF:
    text_ratio  = text block area / page area
    image_ratio = image/drawing area / page area

    text_ratio > 0.70, image_ratio < 0.20  → "text"
    image_ratio > 0.50, text_ratio < 0.20  → "multimodal"
    text < 0.05 AND image < 0.05           → "skip"
    both 0.20–0.70                         → Layer 2

  Layer 2 — Pillow (ambiguous only):
    high color_variance OR high edge_density  → "multimodal"
    otherwise                                 → "mixed"

  Table override — pdfplumber:
    ≥1 table detected → page_type = "table" (overrides Layer 1/2 result)

Non-PDF:
  Excel sheet → "table"
  YAML file   → "structured_text"
  JPEG/PNG    → "multimodal"

Write to MongoDB page_profiles{} with fields:
  doc_id, page_number, page_type, detected_elements,
  text_ratio, image_ratio, has_tables,
  processing_recommendation, estimated_text_tokens, created_at

Print classification report to console:
  "Page  1 | skip       | text_ratio=0.02, image_ratio=0.03"
  "Page  4 | text       | text_ratio=0.78, image_ratio=0.05"
  "Page  8 | multimodal | text_ratio=0.12, image_ratio=0.65"
  "Page 13 | table      | pdfplumber: 1 table detected"

=== PART B: CHUNKING + EMBEDDING (uses Google APIs) ===

PRE-FLIGHT:
  Count multimodal pages → estimate Gemini Vision calls
  Count all text/table chunks → estimate text-embedding-004 calls
  If Gemini calls > DRY_RUN_THRESHOLD (.env, default 10):
    Print warning: "Estimated {N} Gemini calls. Confirm? [y/N]"
    If not confirmed → exit without API calls

PROCESS per page_type:

"text":
  PyMuPDF page.get_text() extract
  Split at heading boundaries (lines matching ^\d+\.\d+ or ALL CAPS)
  Target 500-800 tokens per chunk
  genai.embed_content(model="models/text-embedding-004",
    content=chunk_text, task_type="RETRIEVAL_DOCUMENT")
  Store to doc_embeddings{} — gcs_image_path=None

"table":
  pdfplumber extract → Markdown table format
  One table = one chunk
  Same embedding as text — task_type="RETRIEVAL_DOCUMENT"
  Store to doc_embeddings{} — gcs_image_path=None

"multimodal":
  PyMuPDF render page PNG at zoom=2 (high resolution)
  Save to /output/flat-images/{doc_id}_page_{page_number}.png
  Upload to fake-gcs bucket "rag-fl-documents" key {doc_id}.{page_number}
  Gemini 1.5 Flash prompt:
    "Describe this page comprehensively: what is shown, key numbers and labels,
    relationships between elements, any data trends visible."
  Embed Gemini description — task_type="RETRIEVAL_DOCUMENT"
  Store to doc_embeddings{} with gcs_image_path="gs://rag-fl-documents/{doc_id}.{page_number}"

"mixed":
  a. Extract text → text chunk (chunk_index=0, same as "text" flow)
  b. Render full page PNG → multimodal chunk (chunk_index=1, same as "multimodal" flow)
  Both chunks stored to doc_embeddings{} with same page_number

"skip":
  Log: "Page N: skip — no embedding created"
  No doc_embeddings record

MEMORY (critical for 300MB ROSHN files):
  After processing each page: del all PyMuPDF page objects, PIL images, byte buffers
  Log memory every 10 pages: "Page {N}: {X}MB RSS"

BATCH EMBEDDING:
  Max 100 chunks per text-embedding-004 API call
  Collect chunks in batches before calling API

=== PART C: INSPECTION REPORT ===

After processing each document, print:
  "=== EMBEDDING INSPECTION REPORT ==="
  "Document: {filename} | {total_pages} pages | {total_chunks} chunks | {gemini_calls} Gemini calls"
  "Page  1 | skip       | 0 chunks | —"
  "Page  4 | text       | 3 chunks | 'Planning principles state that mixed-use...'"
  "Page  8 | multimodal | 1 chunk  | Gemini: 'Radial diagram with 6 sectors showing...'"
  "Page 13 | table      | 1 chunk  | '| FAR | Heights | Population |'"

=== PART D: DOCUMENT METADATA EXTRACTION ===

At ingest (update Phase 2 documents{} record or do it at processing time):

1. content_hash: sha256(file_bytes) — computed always
2. Check MongoDB: if content_hash exists → set is_duplicate_of=existing_doc_id, skip embedding
3. report_period extraction — try in order:
   a. Filename: regex for patterns like "January_2025", "Jan2025", "2025-01", "Q1_2025"
   b. PDF metadata: fitz.open(file).metadata.get("creationDate") or "modDate"
   c. First-page text: scan first 500 chars for date patterns
   d. Header/footer: pdfplumber page 1, extract top 30px and bottom 30px text
   e. If nothing found: report_period=None, period_confidence="none"
4. Upload audit: upload_timestamp=datetime.utcnow(), uploaded_by from request header

=== ENTRY POINTS ===

CLI (direct file):
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf --classify-only
  python services/rag-fl/pipeline.py --all   # all docs with status=UPLOADED in MongoDB

FastAPI endpoint (for UI integration):
  POST /process {doc_id: str}
  GET  /document/{doc_id}/status
  GET  /document/{doc_id}/pages
  GET  /document/{doc_id}/chunks/{page_number}
  GET  /documents

=== TEST SEQUENCE ===

Test 1 — Schema check (zero cost):
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf --classify-only
  Verify page_profiles written, all schema fields present

Test 2 — Full pipeline, smallest doc (protect API key):
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf
  Check:
    Page 8 (heatmap) → chunk_type=multimodal, gcs_image_path populated, chunk_text=Gemini desc
    Page 7 (table) → chunk_type=table, chunk_text=Markdown
    Page 1 → chunk_type=text

Test 3 — Comparison test (Harsh's explicit request):
  python services/rag-fl/pipeline.py --file tests/sample-docs/Apartment_Specialists_Churn_Jan2025.xlsx
  python services/rag-fl/pipeline.py --file tests/sample-docs/churn_table_embedded.pdf
  python services/rag-fl/pipeline.py --file tests/sample-docs/churn_table_screenshot.pdf
  Compare extraction output:
    Excel: column count, row count, all values present in Markdown?
    PDF embedded: same columns/rows? any cells merged incorrectly?
    PDF screenshot: Gemini description — does it mention column names and approximate values?

Test 4 — ROSHN Part 01 (larger doc):
  python services/rag-fl/pipeline.py --file "tests/sample-docs/guidelines_part_01_pages_1-15.pdf"
  Check: Pages 1-2 = skip, isometric diagrams = multimodal, FAR pages = table

Test 5 — All 5 sample docs:
  python services/rag-fl/pipeline.py --all

=== MONGODB VALIDATION COMMANDS ===
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.countDocuments({})"
docker compose exec mongo mongosh ragfl --eval "db.doc_embeddings.findOne({chunk_type:'multimodal'})"
docker compose exec mongo mongosh ragfl --eval "db.page_profiles.countDocuments({})"
docker compose exec mongo mongosh ragfl --eval "db.documents.findOne({},{content_hash:1,report_period:1,period_confidence:1,upload_timestamp:1})"

Generate docs/phase_summaries/phase_3_summary.md with:
- Actual Gemini call counts per document
- Comparison test results (Excel vs PDF-embedded vs PDF-screenshot)
- Any deviations from ARCHITECTURE.md schema
```

---

## Phase 4 Prompt — Next.js Observability UI

**Send to Claude Code:**

```
Read ARCHITECTURE.md, PHASES.md, docs/phase_summaries/phase_3_summary.md.

Phase 3 is complete. Building Phase 4: Next.js Observability UI.

Harsh's exact words: "If you can have a UI or interface which can pick a file
and explain what exactly is held there."

This is a RESEARCH UI — not production. Clarity > polish. Built for 30-min syncs with Harsh.
Stack: Next.js + Tailwind CSS. Port 3001. Add to docker-compose.yml.

=== UI LAYOUT (three panels) ===

LEFT PANEL — File List:
  Data: GET /documents
  Show per row: filename | format badge | page count | chunk count | status
  Highlight selected doc
  Upload button at top → POST /ingestion/ingest
  After upload: show "Process" button → POST /process {doc_id}
  Processing: poll GET /document/{doc_id}/status every 3s, show progress bar

CENTER PANEL — Page Explorer:
  Data: GET /document/{doc_id}/pages
  Show per row: page number | type badge (color-coded) | chunk count
  Badge colors: text=blue, table=green, multimodal=purple, mixed=orange, skip=gray
  Click row → expand inline:
    text chunk:       show full chunk_text in monospace
    table chunk:      render Markdown table as HTML <table>
    multimodal chunk: show PNG image (proxy via backend) + Gemini desc below
  Dim/collapse other pages when one is expanded
  Show "768-dim ✓" indicator per chunk to confirm embedding is stored

RIGHT PANEL — Search:
  Input: "Ask anything about this document..."
  Submit → POST /search/within/{doc_id} {query, top_k=5}
  Results: score bar | page badge | chunk_type icon | text snippet (first 200 chars)
  Citation label below each result
  Click result → scroll center panel to that page and expand it

TOP BAR:
  App title "RAG-FL Observability"
  Selected doc name (breadcrumb)
  FORCE_MIXED_MODE indicator (show current env var value)

=== GCS IMAGE PROXY (avoid CORS) ===
Add to rag-fl FastAPI:
  GET /image/{doc_id}/{page_number}
  → fetch from fake-gcs internally → stream bytes to browser
  → Content-Type: image/png

=== NEW ENDPOINTS FOR UI (add to services/rag-fl/main.py) ===
GET /documents                             list all docs with chunk_count
GET /document/{doc_id}/pages               per-page type + chunk count
GET /document/{doc_id}/chunks/{page_n}     chunk details for one page
GET /document/{doc_id}/status              processing progress
GET /image/{doc_id}/{page_number}          GCS image proxy

=== DOCKER ===
Add to docker-compose.yml:
  services:
    ui:
      build: ./services/ui
      ports: ["3001:3001"]
      environment:
        - NEXT_PUBLIC_INGESTION_API=http://localhost:8001
        - NEXT_PUBLIC_RAG_FL_API=http://localhost:8002

Generate docs/phase_summaries/phase_4_summary.md.
```

---

## Phase 5 Prompt — Citation Engine

**Send to Claude Code:**

```
Read ARCHITECTURE.md, PHASES.md, docs/phase_summaries/phase_4_summary.md.

Building Phase 5: Citation Engine.

Delivers Harsh requirement #1: exact page citations like Perplexity/Gemini/ChatGPT.
See ARCHITECTURE.md Citation Format section for format by source type.

Endpoints:
  POST /citations/generate {chunk_ids: [...]}
    → [{label, page_number, doc_id, deep_link, chunk_type}]
  GET /citations/preview/{doc_id}/{page}   → tooltip snippet
  GET /provenance/document/{doc_id}        → full page breakdown
  GET /provenance/chunk/{chunk_id}         → full provenance trail for one chunk

Rules:
  Adjacent pages ±1 from same doc → merge into one citation
  Deep link text/table  → PDF page anchor (#page=N)
  Deep link multimodal  → GET /image/{doc_id}/{page_number} (1hr signed URL or proxy)

Citation cache: MongoDB citation_cache{}, TTL 1hr, key=sha256(sorted chunk_ids).

Validation:
  Churn EDA page 7 → "Churn EDA Report, Page 7, Table 4: Churn by Internet Service"
  ROSHN Part 01 multimodal page → label includes "Figure:" + Gemini desc first 10 words
  Excel chunk → "Churn_Jan2025.xlsx, Sheet: Monthly_Churn_Report, Rows 5–10"

Generate docs/phase_summaries/phase_5_summary.md.
```

---

## Phase 6 Prompt — Search & Retrieval API

**Send to Claude Code:**

```
Read ARCHITECTURE.md, PHASES.md, docs/phase_summaries/phase_5_summary.md.

Building Phase 6: Search & Retrieval API.

CRITICAL: query embedding uses task_type="RETRIEVAL_QUERY" (asymmetric from storage).
Always call shared/utils/vector_search.py — never raw MongoDB query.

Endpoints:
  POST /search {query, top_k=5, filters={doc_ids, format, report_period}, include_multimodal=true}
  POST /search/within/{doc_id} {query, top_k=5}
  GET /document/{doc_id}/summary

Chronological filter:
  filters.report_period="2025-01" → only search docs where report_period="2025-01"
  filters.report_series="monthly_churn" → search all months within that series

Query cache: Redis 1hr, key=sha256(query+filters).
Target: <500ms p95.

Response shape (see ARCHITECTURE.md — must be Next.js UI compatible).

End-to-end validation:
  "what is FAR for medium density?"
    → ROSHN Part 01, Page ~13, score > 0.85
  "what is churn rate for fiber optic?"
    → Churn EDA Report, Page 7, Table 7
  "show me churn data from January 2025"
    → filter by report_period="2025-01", returns Excel chunks


Do not generate phase_6_summary.md yet — wait until I confirm all endpoints
are working and validation passes. Then I will ask for the summary.

---

## Debugging Tips

**Schema mismatch:**
```
Stop. Re-read ARCHITECTURE.md Canonical Chunk Schema.
The field [X] must be [Y]. Do not skip any field. Harsh is explicit about this.
```

**FORCE_MIXED_MODE usage:**
```
Testing fast with small doc → set FORCE_MIXED_MODE=true in .env
Production or API cost awareness → FORCE_MIXED_MODE=false
Never hardcode this in application code.
```

**Duplicate embedding detected:**
```
Check content_hash: db.documents.findOne({content_hash: "<hash>"})
If found → is_duplicate_of should be set, pipeline should not re-embed
```

**Session too long, phase incomplete:**
```
Pause. Commit current state.
Generate partial phase_3_summary.md noting what is done and what remains.
Continue next session.
```

---

## Key Commands

```powershell
docker compose ps
docker compose up -d
docker compose down -v                       # wipe all data
docker compose logs -f rag-fl
docker compose exec mongo mongosh ragfl

# Pipeline
python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf --classify-only
python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf
python services/rag-fl/pipeline.py --all

# Upload
curl.exe -X POST http://localhost:8001/ingest -F "file=@tests/sample-docs/Churn_EDA_Report.pdf"
```

---

## Environment Variables (.env)

```bash
GOOGLE_API_KEY=                       # Harsh's Google AI API key
MONGODB_URI=mongodb://mongo:27017/ragfl?replicaSet=rs0
MONGODB_DB=ragfl
GCS_ENDPOINT=http://fake-gcs:4443
GCS_BUCKET=rag-fl-documents
REDIS_URL=redis://redis:6379
ENVIRONMENT=development
FORCE_MIXED_MODE=false                # true = Abhinav's mixed-default, higher Gemini cost
DRY_RUN_THRESHOLD=10                  # Gemini calls before confirmation required
INPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/input
OUTPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/output
INGESTION_PORT=8001
RAG_FL_PORT=8002
CITATION_PORT=8003
SEARCH_PORT=8004
UI_PORT=3001
LIBREOFFICE_URL=http://libreoffice:3000
```