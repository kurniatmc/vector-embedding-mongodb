# RAG-FL System Architecture
> **Claude Code Context File** — Read this file COMPLETELY at the start of every session before writing any code.
> Last updated: March 2026 — Post Harsh Meeting (Sync on Embedding)

---

## Project Overview

**rag-fl** is a multimodal RAG (Retrieval-Augmented Generation) embedding pipeline.
It processes documents of multiple formats, generates vector embeddings, and stores them in MongoDB
for semantic search with full citation support (page-level provenance).

### Two Core Requirements from Harsh (Non-Negotiable)

**1. Multimodal Explainability**
Every search result must cite the exact source — not just the filename. If a document has 25 pages,
the answer must show which specific page contributed, with a deep link to that page.
Style reference: Perplexity, Google Gemini, ChatGPT citations.
For PDF → exact page number + section. For Excel → sheet + row range. For YAML → key path.
For multimodal pages → rendered image + Gemini description + signed GCS URL.

**2. Multi-Format Support**
Pipeline must process PDF, Excel, YAML, JPEG, PNG, PPTX, DOCX today, and be architected so
adding new formats = adding one new Processor class, nothing else.

### Harsh's Pivot (from Sync on Embedding meeting)
> "No batching. We are not talking about productization. We are talking about explainability.
> If you give a PDF, what are the embeddings? If I go to page 4, does it make sense?
> If you can have a UI which can pick a file and explain what exactly is held there."

Focus order: per-page analysis → embedding → observability UI → citation engine → search.
File Ledger / Batch Orchestration is DEFERRED — already exists in Harsh's production pipeline.

---

## BMP Architecture Alignment

```
                    INPUT SOURCES
     manual upload | folder watcher | OneDrive webhook
                           │
                           ▼
              ┌─────────────────────────┐
              │   Format Registry       │  Phase 2 ✅
              │   7 processors          │
              │   MIME → Processor      │
              └────────────┬────────────┘
                           │  GCS: physical file
                           │  MongoDB documents{}: metadata
                           ▼
              ┌─────────────────────────┐
              │   rag-fl pipeline       │  Phase 3
              │   Per-page classify     │
              │   Chunk + Embed         │
              │   Store vectors         │
              └────────────┬────────────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
     MongoDB (vectors)            GCS Storage
     doc_embeddings               {doc_id}.{page_number}
     page_profiles                (flat images PNG)
     documents
                           │
                           ▼
              ┌─────────────────────────┐
              │   Next.js UI            │  Phase 4
              │   Observability         │
              │   Pick file → explore   │
              └─────────────────────────┘
```

---

## Repository Structure

```
rag-fl/
├── ARCHITECTURE.md
├── PHASES.md
├── CLAUDE_CODE_GUIDE.md
├── PHASE_SUMMARY_TEMPLATE.md
├── .env / .env.example
├── Makefile
├── docker-compose.yml
├── services/
│   ├── ingestion/          Phase 2 ✅ — Format Registry + file intake
│   ├── rag-fl/             Phase 3   — Per-page analysis + embedding pipeline
│   ├── ui/                 Phase 4   — Next.js observability interface
│   ├── citation-engine/    Phase 5   — Provenance + citations
│   └── search-api/         Phase 6   — Query + retrieval
├── shared/
│   ├── schemas/            Canonical Chunk Schema (Pydantic)
│   ├── contracts/          Inter-service API shapes
│   └── utils/
│       ├── gcs_client.py
│       ├── mongo_client.py
│       └── vector_search.py  ← auto-switch local cosine / Atlas $vectorSearch
├── infra/
│   ├── mongo-init/         Collections + vector index scripts
│   └── cloudrun/           Phase 7 deployment configs
├── tests/
│   ├── sample-docs/        All 5 test PDFs + comparison Excel/PDF test set
│   └── phase_tests/
└── docs/
    ├── phase_summaries/    Generated after each phase
    └── decisions/
```

---

## Technology Stack

| Component | Technology | Reason |
|---|---|---|
| Vector Store | MongoDB Community (local) / Atlas (prod) | $vectorSearch on Atlas, cosine local |
| Embeddings | Google text-embedding-004 (768 dim) | Asymmetric DOCUMENT/QUERY task types |
| Vision | Gemini 1.5 Flash | Page description → text for embedding |
| PDF | PyMuPDF + pdfplumber | Structure analysis + table extraction |
| Image Analysis | Pillow | Free, local, no API cost |
| Format Conversion | Gotenberg/LibreOffice | PPTX/DOCX → PDF |
| Queue | Redis | Async workers + cache |
| Local GCS | fake-gcs-server | Identical API to real GCS |
| Framework | FastAPI | Async, type-safe |
| UI | Next.js + Tailwind | Observability interface |
| Container | Docker + docker-compose | Local = Production parity |

Not using: LangChain, LangGraph, batch orchestration (deferred).

---

## Sample Documents for Testing

| File | Pages | Key Content Types |
|---|---|---|
| guidelines_part_01_pages_1-15.pdf | 15 | cover/skip, text, mixed, multimodal (isometric diagrams) |
| guidelines_part_02_pages_16-30.pdf | 15 | multimodal (microclimate), table (FAR metrics), mixed |
| Churn_EDA_Report.pdf | 9 | text, table, mixed (KPI cards), multimodal (Pearson heatmap) |
| Titanic_data_pdf_1.pdf | 11 | mixed, multimodal (charts/scatter), table (cross-tab) |
| Machine Learning in Detecting Fraud Literature Review.pdf | varies | text-heavy, some mixed, some table |

### Comparison Test Files (Harsh's request — table extraction accuracy)
| File | Description | Purpose |
|---|---|---|
| CustomerChurn_Jan2025.xlsx | 15 customers, 10 cols, 3 sheets | Source of truth — native Excel extraction |
| CustomerChurn_Jan2025 - Table.pdf | Same data copy-pasted as Word table → PDF | Test: pdfplumber structured extraction |
| ChurnCustomer_Jan2025.pdf | Same data as screenshot image → PDF | Test: multimodal flow, Gemini Vision extraction |

The three files above must produce comparable embeddings despite different extraction paths.
This validates that the pipeline handles all real-world table formats.

### Copy Sample Docs (Windows CMD)
```cmd
copy "E:\Work\TMC - Roshn\Work\Embedding Projects POC\sample data\guidelines\guidelines_part_01_pages_1-15.pdf" "tests\sample-docs\"
copy "E:\Work\TMC - Roshn\Work\Embedding Projects POC\sample data\guidelines\guidelines_part_02_pages_16-30.pdf" "tests\sample-docs\"
copy "E:\Work\TMC - Roshn\Work\Embedding Projects POC\sample data\Churn_EDA_Report.pdf" "tests\sample-docs\"
copy "E:\Work\TMC - Roshn\Work\Embedding Projects POC\sample data\Titanic_data_pdf_1.pdf" "tests\sample-docs\"
copy "E:\Work\TMC - Roshn\Work\Embedding Projects POC\sample data\Machine Learning in Detecting Fraud Literature Review.pdf" "tests\sample-docs\"
```

### Expected Page Classifications
```
ROSHN Part 01:  Pages 1-2 skip | Pages 3-5 text | Pages 6-8 mixed | Pages 9-12 multimodal | Pages 13-15 table
ROSHN Part 02:  Pages 16-18 multimodal | Pages 19-25 text/mixed | Pages 26-30 multimodal
Churn EDA:      Page 1 text | Pages 2-3 table | Page 4 mixed | Pages 5-6 multimodal | Page 7 mixed | Page 8 multimodal | Page 9 text
Titanic:        Pages 1-2 mixed | Pages 3-4 multimodal | Page 5 table | Page 6 mixed | Pages 7-11 multimodal
Fraud Review:   Mostly text | Some mixed | Some table
```

---

## Canonical Chunk Schema

> **SCHEMA ALIGNMENT IS MANDATORY** — Harsh's explicit requirement.
> Every chunk in MongoDB doc_embeddings MUST have ALL these fields. No exceptions.
> Align on this schema before any implementation proceeds.

```python
{
  # Identity
  "chunk_id":   str,        # UUID — primary key
  "doc_id":     str,        # FK → documents collection

  # Provenance — drives citation requirement
  "page_number":    int,    # 1-indexed. Excel=sheet index. YAML=1. Image=1.
  "bounding_box": {         # Pixel coords of chunk on page. None for non-visual.
      "x0": float, "y0": float, "x1": float, "y1": float
  },
  "section_title":  str,    # e.g. "2.1 Medium Density" — detected from headings
  "chunk_index":    int,    # Position within page, 0-indexed (0=text, 1=visual for mixed)

  # Format-specific provenance
  "format_provenance": {
    # PDF:   {"original_format": "pdf", "pdf_page_label": str}
    # Excel: {"original_format": "xlsx", "sheet_name": str, "row_start": int, "row_end": int}
    # YAML:  {"original_format": "yaml", "key_path": str}
    # Image: {"original_format": "jpeg/png", "original_filename": str}
    # PPTX:  {"original_format": "pptx", "slide_number": int}
  },

  # Content
  "chunk_type":      str,   # "text" | "table" | "multimodal"
  "chunk_text":      str,   # Raw text, Markdown table, or Gemini Vision description
  "gcs_image_path":  str,   # "gs://rag-fl-documents/{doc_id}.{page_number}" | None

  # Embedding
  "embedding":           list[float],  # 768 dims, text-embedding-004
  "embedding_model":     str,          # "models/text-embedding-004"
  "embedding_task_type": str,          # Always "RETRIEVAL_DOCUMENT" when storing

  # Timestamps
  "created_at":  datetime,
  "updated_at":  datetime
}
```

---

## Document Schema — with Chronological Metadata

> **Harsh's requirement:** pipeline must support chronological ordering of recurring reports
> (e.g. monthly ops reports). Upload timestamp alone is NOT sufficient — it reflects when
> someone uploaded, not what period the document covers.
> This is NOT an edge case — Harsh called it "the main case you will deal with in and out."

```python
# MongoDB documents{} collection
{
  # Identity
  "doc_id":            str,       # UUID
  "filename":          str,
  "original_format":   str,       # "pdf" | "xlsx" | "yaml" | "jpeg" | "png" | "pptx" | "docx"
  "gcs_path":          str,       # gs://rag-fl-documents/{doc_id}/{filename}

  # Processing state
  "total_pages":        int,
  "status":             str,      # "UPLOADED" | "PROCESSING" | "EMBEDDED" | "FAILED"
  "source_channel":     str,      # "manual_upload" | "folder_watcher" | "onedrive"
  "format_provenance":  dict,     # processor.extract_provenance() output

  # ── DEDUPLICATION ──────────────────────────────────────────────────────
  # Prevents two users uploading the same file from double-embedding it.
  # At ingest: compute sha256(file_bytes). Check if already in MongoDB.
  # If exists: skip embedding, record upload event only.
  "content_hash":       str,      # sha256(file_bytes) — computed at ingest, always
  "is_duplicate_of":    str,      # doc_id of original, or None

  # ── CHRONOLOGICAL METADATA ─────────────────────────────────────────────
  # Best-effort extraction at ingest time. Sources tried in order:
  #   1. Filename parsing: "January_2025_Operations_Report.pdf" → 2025-01
  #   2. PDF metadata:     fitz.open().metadata["creationDate"] if present
  #   3. First-page text:  scan first 500 chars for date patterns
  #   4. Header/footer:    pdfplumber extract top/bottom strip of page 1
  # If none found → report_period=None, period_confidence="none"
  "report_series":        str,    # e.g. "monthly_churn" — user-defined or auto-detected
  "report_period":        str,    # "2025-01" ISO YYYY-MM, or "2025-Q1", or None
  "report_period_start":  datetime,  # First day of period, or None
  "report_period_end":    datetime,  # Last day of period, or None
  "report_frequency":     str,    # "monthly" | "quarterly" | "annual" | "ad-hoc" | None
  "period_confidence":    str,    # "high" | "medium" | "low" | "none"
  "extraction_method":    str,    # "filename" | "pdf_metadata" | "first_page_text" | "none"

  # ── UPLOAD AUDIT ───────────────────────────────────────────────────────
  "upload_timestamp":   datetime,  # When file was uploaded — NOT the report period
  "uploaded_by":        str,       # Email/user who uploaded — for dedup awareness

  "created_at":         datetime,
  "updated_at":         datetime
}
```

### Why content_hash matters for large recurring reports
```
Without deduplication:
  User A uploads "Jan 2025 Report.pdf" (300MB) → 300 Gemini calls, all embeddings stored
  User B uploads same file 2 weeks later       → 300 MORE Gemini calls, duplicate embeddings
  Vector search now returns duplicate results for every query

With content_hash:
  User A uploads → sha256 computed → not found → process normally
  User B uploads → sha256 computed → FOUND → skip embedding, log "duplicate of doc_id X"
  Zero wasted API cost, clean vector store
```

---

## MongoDB Collections — Full Provenance Model

```
documents{}       → doc_id, filename, original_format, gcs_path,
                    total_pages, status, source_channel, format_provenance,
                    content_hash, is_duplicate_of,
                    report_series, report_period, report_period_start, report_period_end,
                    report_frequency, period_confidence, extraction_method,
                    upload_timestamp, uploaded_by,
                    created_at, updated_at

page_profiles{}   → doc_id, page_number, page_type, detected_elements,
                    text_ratio, image_ratio, has_tables,
                    processing_recommendation, estimated_text_tokens,
                    created_at

doc_embeddings{}  → all Canonical Chunk Schema fields above + 768-dim vector index

citation_cache{}  → cache_key, citations[], expires_at (TTL 1hr)

[DEFERRED]
file_ledger{}     → doc_id, status, batch_id, retry_count,
                    state_history [{state, timestamp, reason}]
```

---

## Format Registry Pattern

```python
class BaseProcessor(ABC):
    def validate(self, file_bytes: bytes) -> bool: ...
    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput: ...
    def extract_provenance(self, normalized: NormalizedOutput) -> dict: ...

REGISTRY = {
    "application/pdf":                                                             "PDFProcessor",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":          "ExcelProcessor",
    "application/vnd.ms-excel":                                                    "ExcelProcessor",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":  "PPTXProcessor",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":    "DOCXProcessor",
    "application/x-yaml":   "YAMLProcessor",
    "text/yaml":            "YAMLProcessor",
    "text/x-yaml":          "YAMLProcessor",
    "image/jpeg":           "ImageProcessor",
    "image/png":            "ImageProcessor",
}
```

---

## Per-Page Classification Logic

Phase 3 only. Gemini Vision NOT called here — zero API cost.

```
FORCE_MIXED_MODE=true  (env var, default: false)
→ Skip all classification, treat ALL PDF pages as "mixed"
→ Use for: development speed, small test docs, when Abhinav's suggestion needed
→ Cost warning: every page triggers Gemini Vision + text embedding

FORCE_MIXED_MODE=false (default for production)
→ Run full classification pipeline below

Layer 1 — PyMuPDF (every page, free):
  text_ratio  = text block area / page area
  image_ratio = image/drawing area / page area

  text_ratio > 0.70, image_ratio < 0.20   → "text"
  image_ratio > 0.50, text_ratio < 0.20   → "multimodal"
  text < 0.05 AND image < 0.05            → "skip"  (blank/dark cover)
  both 0.20–0.70                          → Layer 2

Layer 2 — Pillow (ambiguous pages only):
  high color_variance   → "multimodal" (infographic/diagram)
  high edge_density     → "multimodal" (line diagram/flow chart)
  otherwise             → "mixed"

Table override (runs after Layer 1):
  pdfplumber detects ≥1 table → page_type = "table"  (overrides text/multimodal)

Non-PDF logical pages:
  Excel sheet  → "table"
  YAML file    → "structured_text"
  JPEG/PNG     → "multimodal"
```

---

## Embedding Strategy — text-embedding-004

### Asymmetric Task Types — MANDATORY, NEVER MIX

```python
# Phase 3: storing chunks — ALWAYS RETRIEVAL_DOCUMENT
result = genai.embed_content(
    model="models/text-embedding-004",
    content=chunk_text,
    task_type="RETRIEVAL_DOCUMENT"
)

# Phase 6: user query — ALWAYS RETRIEVAL_QUERY
result = genai.embed_content(
    model="models/text-embedding-004",
    content=user_query,
    task_type="RETRIEVAL_QUERY"
)
```

Using same task_type for both degrades retrieval quality significantly. This is asymmetric by design.

---

## Vector Search Strategy — Local vs Production

```python
# shared/utils/vector_search.py
def vector_search(collection, query_vector, top_k=5, filter_query=None):
    """Single entry point. Auto-switches by ENVIRONMENT env var."""
    if os.getenv("ENVIRONMENT") == "production":
        return _atlas_search(collection, query_vector, top_k, filter_query)
    return _local_search(collection, query_vector, top_k, filter_query)

def _atlas_search(collection, query_vector, top_k, filter_query):
    pipeline = [{"$vectorSearch": {
        "index": "embedding_index", "path": "embedding",
        "queryVector": query_vector, "numCandidates": top_k * 10, "limit": top_k,
        **( {"filter": filter_query} if filter_query else {} )
    }}, {"$addFields": {"score": {"$meta": "vectorSearchScore"}}}]
    return list(collection.aggregate(pipeline))

def _local_search(collection, query_vector, top_k, filter_query):
    projection = {"embedding": 1, "chunk_id": 1, "chunk_text": 1, "chunk_type": 1,
                  "page_number": 1, "doc_id": 1, "gcs_image_path": 1,
                  "section_title": 1, "format_provenance": 1, "bounding_box": 1}
    candidates = list(collection.find(filter_query or {}, projection))
    for doc in candidates:
        if doc.get("embedding"):
            doc["score"] = cosine_similarity(query_vector, doc["embedding"])
    return sorted([d for d in candidates if "score" in d],
                  key=lambda x: x["score"], reverse=True)[:top_k]
```

Migration to Atlas (Phase 7): set ENVIRONMENT=production, create Atlas index. Zero code changes.

---

## File System Contracts

```
/input/                  ← Drop files here (Windows bind mount)
/output/
  ├── embedding-db/      ← Embedding artifacts
  └── flat-images/       ← Rendered page PNGs before GCS upload
                            naming: {doc_id}_page_{page_number}.png

GCS bucket:  rag-fl-documents
GCS key:     {doc_id}.{page_number}    e.g. a3f9c2b1.12
```

---

## Citation Format by Source Type

```
PDF text:        "ROSHN Guidelines Part 01, Page 8, Section 2.1 Medium Density"
PDF multimodal:  "ROSHN Guidelines Part 01, Page 10, Figure: Microclimate Studies"
PDF table:       "Churn EDA Report, Page 7, Table 4: Churn by Internet Service"
Excel:           "Churn_Jan2025.xlsx, Sheet: Monthly_Churn_Report, Rows 5–10"
YAML:            "config.yaml, Key: training.optimizer.learning_rate"
Fraud Review:    "ML Fraud Detection Review, Page 4, Section 3.2 Related Work"
```

Adjacent pages (consecutive or ±1) from same doc → merge into one citation.

Deep links:
- PDF text/table → page anchor (#page=N)
- Multimodal → signed GCS URL (1hr TTL) → serves actual rendered PNG

---

## Local vs Production Parity

| Config | Local | Production |
|---|---|---|
| GCS_ENDPOINT | http://fake-gcs:4443 | https://storage.googleapis.com |
| MONGODB_URI | mongodb://mongo:27017/ragfl?replicaSet=rs0 | Atlas URI |
| GOOGLE_API_KEY | Harsh's key | Same / Service Account |
| ENVIRONMENT | development | production |
| FORCE_MIXED_MODE | true (dev testing) | false |
| DRY_RUN_THRESHOLD | 10 | 100 |
| Vector search | cosine similarity | Atlas $vectorSearch |

Rule: Zero conditional logic in application code. Only .env values differ.

---

## Cost Safeguards

1. `?dry_run=true` on every endpoint — estimates only, writes nothing
2. Pre-flight Phase 3 — count estimated Gemini Vision calls before processing
3. If calls > DRY_RUN_THRESHOLD → pause, print warning, require confirmation
4. `FORCE_MIXED_MODE=false` in production — do not Gemini-call pure text pages
5. content_hash deduplication — never re-embed a file already processed
6. Circuit breaker — 5 Gemini failures in 10 min → text-only fallback, flag `needs_vision_retry=true`

---

## Windows Development Setup

Project path: `E:\Work\TMC - Roshn\Work\Embedding Projects POC\`

```yaml
# docker-compose.yml — use ENV vars for paths with spaces
volumes:
  - "${INPUT_DIR}:/input"
  - "${OUTPUT_DIR}:/output"
```

```bash
# .env — forward slashes for Docker even on Windows
INPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/input
OUTPUT_DIR=E:/Work/TMC - Roshn/Work/Embedding Projects POC/output
FORCE_MIXED_MODE=false
DRY_RUN_THRESHOLD=10
```

```powershell
# Create input/output folders first
mkdir "E:\Work\TMC - Roshn\Work\Embedding Projects POC\input"
mkdir "E:\Work\TMC - Roshn\Work\Embedding Projects POC\output\embedding-db"
mkdir "E:\Work\TMC - Roshn\Work\Embedding Projects POC\output\flat-images"

# curl on Windows (built-in)
curl.exe -X POST http://localhost:8001/ingest -F "file=@tests/sample-docs/Churn_EDA_Report.pdf"

# Always run Claude Code from project root
cd "E:\Work\TMC - Roshn\Work\Embedding Projects POC\code\rag-fl"
claude
```

---

## Authentication

Current: `GOOGLE_API_KEY` in .env
Future: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`
No code changes required — Google SDK auto-detects both.