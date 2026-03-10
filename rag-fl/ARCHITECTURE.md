# RAG-FL System Architecture
> **Claude Code Context File** — Read this file COMPLETELY at the start of every session before writing any code.
> Last updated: 2026-03-10 — Phase 3F (Full-Page-as-Image) complete

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

## System Architecture — Complete Flow (Phases 1-6)

```
╔══════════════════════════════════════════════════════════════════════════╗
║  INPUT SOURCES                                                           ║
║  Browser upload (UI :3001)  │  CLI: pipeline.py --file <path>           ║
╚════════════════════════════╤═════════════════════════════════════════════╝
                             │
                             ▼
         ┌───────────────────────────────────────┐
         │         Ingestion Service             │  :8001  Phase 2 ✅
         │                                       │
         │  Format Registry (MIME → Processor)   │
         │    PDFProcessor  / ExcelProcessor      │
         │    YAMLProcessor / ImageProcessor      │
         │    PPTXProcessor / DOCXProcessor       │
         │                                       │
         │  • sha256 content_hash deduplication  │
         │  • report_period extraction           │
         │    (filename → PDF metadata → text)   │
         │  • status = UPLOADED → MongoDB        │
         │  • background task → POST /process    │  ← Phase 4.1 ✅
         └──────────────────┬────────────────────┘
                            │  documents{} status=UPLOADED
                            │  httpx background → POST :8004/process
                            ▼
         ┌───────────────────────────────────────────────────────────────┐
         │                   rag-fl Pipeline                             │
         │                                      :8004  Phase 3 ✅        │
         │  ┌─── STEP 1 — 4-LAYER TABLE DETECTION ───────────────────┐  │
         │  │                                                         │  │
         │  │  Strategy 1 — pdfplumber LINES             Phase 3A ✅  │  │
         │  │    find_tables(vertical=lines,horizontal=lines)         │  │
         │  │    → lines_table_rects  (reliable; can suppress visual) │  │
         │  │                                                         │  │
         │  │  Strategy 2 — whitespace word alignment    Phase 3B ✅  │  │
         │  │    extract_words() → x0 cluster (30pt gap)             │  │
         │  │    col consistency ≥40% · multi-line merge <8pt         │  │
         │  │    CID artifact filter · rows[] pre-extracted           │  │
         │  │    → soft_table_rects (heuristic; never suppress visual)│  │
         │  │                                                         │  │
         │  │  Strategy 3 — text+lines (after visual detect) 3C ✅   │  │
         │  │    find_tables(vertical=text, horizontal=lines)         │  │
         │  │    catches horizontal-separator-only tables             │  │
         │  │    → soft_table_rects                                   │  │
         │  │                                                         │  │
         │  │  Validation (all strategies):                           │  │
         │  │    ≥4 non-empty cells · not 1×1 · not all-prose        │  │
         │  └─────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  ┌─── STEP 2 — VISUAL DETECTION ──────────────────────────┐  │
         │  │                                                         │  │
         │  │  get_images(full=True)  → raster + Form XObjects        │  │
         │  │  get_drawings()         → vector chart elements         │  │
         │  │  _cluster_rects(gap=20) → merged visual regions         │  │
         │  │                                                         │  │
         │  │  Large cluster (>25% page):  Phase 3C ✅                │  │
         │  │    _try_split_cluster() renders 0.5x thumbnail          │  │
         │  │    finds whitespace bands (≥95% white rows/cols)        │  │
         │  │    → splits into N distinct sub-region visual elements  │  │
         │  │                                                         │  │
         │  │  Discard check: visual cluster >70% inside              │  │
         │  │    lines_table_rects ONLY (not soft_table_rects)        │  │
         │  │                                                         │  │
         │  │  Pixel fallback:               Phase 3B ✅              │  │
         │  │    if covered_area <50% AND non_white >15%              │  │
         │  │    AND text_ratio <0.5 → add full-page visual           │  │
         │  └─────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  ┌─── STEP 3 — TEXT BLOCK EXTRACTION ─────────────────────┐  │
         │  │                                                         │  │
         │  │  get_text("blocks") → filter:                           │  │
         │  │    • center_y inside any table bbox → skip   Phase 3C ✅│  │
         │  │    • overlap >50% with table bbox   → skip              │  │
         │  │    • overlap >30% with visual bbox  → skip (caption)    │  │
         │  │    remaining blocks → text_elements                     │  │
         │  └─────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  page_type derived from element presence:                     │
         │    visual + anything  → mixed                                 │
         │    visual only        → multimodal                            │
         │    table + text       → mixed                                 │
         │    table only         → table                                 │
         │    text only          → text                                  │
         │    nothing            → skip                                  │
         │                                                               │
         │  ┌─── STEP 4 — PER-ELEMENT CHUNKING + EMBEDDING ──────────┐  │
         │  │                                                         │  │
         │  │  TEXT elements                                          │  │
         │  │    chunk_text_page(exclude_rects=table+visual bboxes)   │  │
         │  │    → heading-bounded 500-800 token chunks               │  │
         │  │    → embed 768-dim RETRIEVAL_DOCUMENT                   │  │
         │  │                                                         │  │
         │  │  TABLE elements                                         │  │
         │  │    if elem has rows[] (whitespace/text+lines):          │  │
         │  │      chunk_whitespace_table() → Markdown                │  │
         │  │    else (pdfplumber lines):                             │  │
         │  │      chunk_specific_table(table_index) → Markdown       │  │
         │  │    CID artifact rejection on final markdown             │  │
         │  │    → embed 768-dim RETRIEVAL_DOCUMENT                   │  │
         │  │                                                         │  │
         │  │  VISUAL elements                                        │  │
         │  │    render_and_upload_visual_region(bbox)                │  │
         │  │      2x zoom clip → PIL whitespace trim + 10px pad      │  │
         │  │      → GCS: {doc_id}.{page} (v0)                       │  │
         │  │              {doc_id}.{page}.v1 (v1) ... .vN            │  │
         │  │    _find_caption_near_visual() → text within 25pt       │  │
         │  │    Gemini 2.0 Flash describe_page_image(png_bytes)      │  │
         │  │    caption + "\n\n" + gemini_description → chunk_text   │  │
         │  │    → embed 768-dim RETRIEVAL_DOCUMENT                   │  │
         │  └─────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  Batch embed (gemini-embedding-001, output_dimensionality=768)│
         │  Circuit breaker: 5 consecutive failures → text fallback      │
         └──────────────────────┬──────────────────┬─────────────────────┘
                                │                  │
                     ┌──────────▼──────────┐  ┌───▼─────────────────────┐
                     │  MongoDB            │  │  GCS (fake-gcs :4443)   │
                     │                     │  │  bucket: rag-fl-documents│
                     │  documents{}        │  │                         │
                     │  page_profiles{}    │  │  {doc_id}.{page}        │
                     │  doc_embeddings{}   │  │    first visual crop    │
                     │    768-dim vectors  │  │  {doc_id}.{page}.v1     │
                     │    gcs_image_path   │  │    second visual crop   │
                     │    format_provenance│  │  {doc_id}.{page}.vN     │
                     │  citation_cache{}   │  │    Nth visual crop      │
                     │    TTL 1hr          │  │                         │
                     └──────────┬──────────┘  └─────────────────────────┘
                                │
                                ▼
         ┌───────────────────────────────────────────────────────────────┐
         │                   Next.js UI                                  │
         │                                      :3001  Phase 4 ✅        │
         │                                                               │
         │  ┌── LEFT PANEL ──────────────────────────────────────────┐  │
         │  │  File list (EMBEDDED only)          Phase 4.1 ✅        │  │
         │  │  + Upload → auto-process → poll → done toast            │  │
         │  │  + ⊞ Compare button when ≥2 files share base name      │  │
         │  │    (strips PureTable_/SS_/etc prefix → normalize)       │  │
         │  └────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  ┌── CENTER — PAGE EXPLORER ──────────────────────────────┐  │
         │  │  Page rows: page_type badge + chunk count               │  │
         │  │  Expand → ChunkCard per chunk:                          │  │
         │  │    header:  [type badge] [📊 Visual?] Chunk N of M      │  │
         │  │             section_title · 768-dim ✓                   │  │
         │  │    sub-hdr: chunk_id (truncated, click-to-copy)         │  │
         │  │    metadata (collapsible): full chunk_id, page,         │  │
         │  │             section, format_provenance, bbox            │  │
         │  │    content:                                             │  │
         │  │      text chunk      → ReactMarkdown (headings/lists)   │  │
         │  │      table chunk     → ReactMarkdown GFM table          │  │
         │  │                        (borders, alternating rows)      │  │
         │  │      multimodal      → PNG (gcsImageUrl → ?v=N)         │  │
         │  │                        "Open full size ↗" link          │  │
         │  │                        ReactMarkdown Gemini description  │  │
         │  └────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  ┌── CENTER — COMPARISON VIEW (when ⊞ Compare clicked) ───┐  │
         │  │  N columns side-by-side, one per file in group          │  │
         │  │  Column header: format badge + filename + fidelity tag  │  │
         │  │    ≡ Full fidelity  (structured table extracted)        │  │
         │  │    ▣ Vision description  (Gemini described screenshot)  │  │
         │  │  Page navigation if multi-page docs                     │  │
         │  │  Each column shows ChunkCards for current page          │  │
         │  └────────────────────────────────────────────────────────┘  │
         │                                                               │
         │  ┌── RIGHT PANEL — SEARCH ────────────────────────────────┐  │
         │  │  POST /search/within/{doc_id}                           │  │
         │  │  Results: score bar + page badge + snippet + citation   │  │
         │  │  Click → scroll + expand target page in center panel    │  │
         │  └────────────────────────────────────────────────────────┘  │
         └───────────────────────────────────────────────────────────────┘
                                │
                                ▼ (same :8004 FastAPI service)
         ┌───────────────────────────────────────────────────────────────┐
         │             Citation Engine  (citation.py router)             │
         │                                      Phase 5 ✅               │
         │  POST /citations/generate   {chunk_ids}                       │
         │    → [{label, page, deep_link, chunk_type}]                   │
         │    cache: MongoDB citation_cache{} TTL 1hr                    │
         │                                                               │
         │  GET  /citations/preview/{doc_id}/{page}                      │
         │  GET  /provenance/document/{doc_id}                           │
         │  GET  /provenance/chunk/{chunk_id}                            │
         └───────────────────────────────────────────────────────────────┘
                                │
                                ▼
         ┌───────────────────────────────────────────────────────────────┐
         │           Search & Retrieval API  (search.py router)          │
         │                                      Phase 6 ✅               │
         │  POST /search                                                  │
         │    query embed → RETRIEVAL_QUERY task_type                    │
         │    filters: doc_ids, format, report_period, report_series     │
         │    include_multimodal toggle                                   │
         │    Redis cache SHA-256 keyed, TTL 1hr                         │
         │                                                               │
         │  POST /search/within/{doc_id}   (UI right panel)              │
         │  GET  /document/{doc_id}/summary                              │
         │                                                               │
         │  Local:  cosine similarity (numpy)                            │
         │  Prod:   Atlas $vectorSearch — zero code change               │
         └───────────────────────────────────────────────────────────────┘
                                │
                                ▼
         ┌───────────────────────────────────────────────────────────────┐
         │  Phase 7 — Cloud Run deployment                    ⬜ TODO    │
         │  ENVIRONMENT=production → Atlas URI + real GCS                │
         │  Zero code changes — only .env values differ                  │
         └───────────────────────────────────────────────────────────────┘
```

---

## UI Panel to API Mapping (Phase 4 + 4.1 + UI Enhancements)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    TOP BAR                                              │
├────────────────────────────────────┬────────────────────────────────────┤
│ UI Feature                         │ API / Logic                        │
├────────────────────────────────────┼────────────────────────────────────┤
│ FORCE_MIXED_MODE indicator         │ GET :8004/config                   │
│ Current document name in breadcrumb│ client state only                  │
└────────────────────────────────────┴────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    LEFT PANEL — File List                               │
├────────────────────────────────────┬────────────────────────────────────┤
│ UI Feature                         │ API / Logic                        │
├────────────────────────────────────┼────────────────────────────────────┤
│ Show EMBEDDED documents only       │ GET :8004/documents → filter       │
│                                    │     status === "EMBEDDED"          │
│ Upload file                        │ POST :8001/ingest                  │
│ Auto-trigger processing            │ background task → POST :8004/      │
│                                    │   process {doc_id}  (Phase 4.1)   │
│ Poll upload status                 │ GET :8001/documents/{doc_id}       │
│ Poll embedding completion          │ GET :8004/documents (by filename)  │
│ Duplicate detection toast          │ POST :8001/ingest → is_duplicate   │
│ Embedding complete toast           │ poll resolves status=EMBEDDED       │
│ ⊞ Compare button (per group)       │ client-side: normalizeBaseName()   │
│   appears when ≥2 files share      │   strips PureTable_/SS_/etc        │
│   the same base filename           │   → detectComparisonGroups()       │
└────────────────────────────────────┴────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│               CENTER PANEL — Page Explorer (normal mode)                │
├────────────────────────────────────┬────────────────────────────────────┤
│ UI Feature                         │ API / Logic                        │
├────────────────────────────────────┼────────────────────────────────────┤
│ Page list with type badges         │ GET :8004/document/{doc_id}/pages  │
│ Expand page → ChunkCard per chunk  │ GET :8004/document/{doc_id}/       │
│                                    │     chunks/{page_number}           │
│ chunk_type badge (colored)         │ chunk.chunk_type from response     │
│ "Chunk N of M" position label      │ chunk.chunk_index + count          │
│ 📊 Visual badge                    │ keyword scan on chunk.chunk_text   │
│ section_title display              │ chunk.section_title from response  │
│ 768-dim ✓ indicator                │ chunk.embedding_dims from response │
│ chunk_id (truncated, copy-to-clip) │ chunk.chunk_id from response       │
│ ▼ Show metadata (collapsible)      │ chunk.format_provenance + bbox     │
│ text chunk → ReactMarkdown         │ react-markdown + remark-gfm        │
│ table chunk → HTML table grid      │ react-markdown GFM table renderer  │
│   (borders, alternating rows,      │   mdTableComponents custom styles  │
│    horizontal scroll if wide)      │                                    │
│ multimodal → PNG image             │ GET :8004/image/{doc_id}/{page}    │
│   correct crop per chunk           │     ?v=N  ← parsed from           │
│   (gcsImageUrl() parses .v{n})     │     chunk.gcs_image_path .v{n}    │
│ "Open full size ↗" link            │ same image URL, target=_blank      │
│ Gemini description → ReactMarkdown │ chunk.chunk_text formatted         │
└────────────────────────────────────┴────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│            CENTER PANEL — Comparison View (⊞ Compare mode)             │
├────────────────────────────────────┬────────────────────────────────────┤
│ UI Feature                         │ API / Logic                        │
├────────────────────────────────────┼────────────────────────────────────┤
│ N columns, one per file in group   │ GET :8004/document/{doc_id}/       │
│ Each column shows page N chunks    │     chunks/{page_number}           │
│   side-by-side simultaneously      │   called in parallel for all docs  │
│ Format badge per column (XLSX/PDF) │ doc.original_format                │
│ ≡ Full fidelity badge              │ no multimodal chunks in response   │
│ ▣ Vision description badge         │ has multimodal chunk in response   │
│ Page navigation (‹ ›)              │ re-fetches chunks for all docs     │
│ ← Back to explorer button          │ client state: setCompareGroup(null)│
│ ChunkCards same as normal mode     │ same rendering, same metadata      │
└────────────────────────────────────┴────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    RIGHT PANEL — Search                                 │
├────────────────────────────────────┬────────────────────────────────────┤
│ UI Feature                         │ API / Logic                        │
├────────────────────────────────────┼────────────────────────────────────┤
│ Search within selected document    │ POST :8004/search/within/{doc_id}  │
│ Score bar (0–100%)                 │ response → score (cosine)          │
│ Page badge + chunk_type badge      │ response → page_number, chunk_type │
│ Text snippet (3-line clamp)        │ response → chunk_text              │
│ Citation label (filename · page)   │ client-side construction           │
│ Click → scroll + expand page       │ client-side only (no API call)     │
└────────────────────────────────────┴────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│          Backend-ready endpoints not yet exposed in UI                  │
├────────────────────────────────────┬────────────────────────────────────┤
│ Feature                            │ API                                │
├────────────────────────────────────┼────────────────────────────────────┤
│ Global cross-document search       │ POST :8004/search                  │
│   with report_period filter        │   {query, filters: {report_period}}│
│ Citation tooltip preview           │ GET :8004/citations/preview/       │
│                                    │     {doc_id}/{page}                │
│ Full document provenance trail     │ GET :8004/provenance/document/     │
│                                    │     {doc_id}                       │
│ Single chunk provenance            │ GET :8004/provenance/chunk/        │
│                                    │     {chunk_id}                     │
└────────────────────────────────────┴────────────────────────────────────┘
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
│   ├── ingestion/          Phase 2 ✅ — Format Registry + file intake + auto-trigger (Phase 4.1)
│   ├── rag-fl/             Phase 3 ✅ — Per-page analysis + embedding pipeline
│   │                       Phase 5 ✅ — Citation Engine (citation.py router)
│   │                       Phase 6 ✅ — Search & Retrieval API (search.py router)
│   └── ui/                 Phase 4 ✅ — Next.js observability interface
│                           Phase 4.1 ✅ — Auto-process polling + EMBEDDED filter
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
| Embeddings | **gemini-embedding-001** (768 dim) | Asymmetric DOCUMENT/QUERY task types. Deviation: originally text-embedding-004, but API key returned 404. gemini-embedding-001 produces identical 768-dim vectors. |
| Vision | **Gemini 2.0 Flash** | Page description → text for embedding. Deviation: originally Gemini 1.5 Flash, but API key returned 404. Gemini 2.0 Flash has identical API + improved quality. |
| PDF | PyMuPDF + pdfplumber | PyMuPDF: visual/text detection. pdfplumber: table extraction (3 strategies). |
| Image Analysis | Pillow | Visual crop whitespace trimming (getbbox). Low-res thumbnail for pixel fallback and cluster splitting. |
| Format Conversion | Gotenberg/LibreOffice | PPTX/DOCX → PDF |
| Queue/Cache | Redis | Search query cache (1hr TTL, SHA-256 keyed) |
| Local GCS | fake-gcs-server | Identical API to real GCS |
| Framework | FastAPI | Async, type-safe. Routers: citation.py (Phase 5), search.py (Phase 6) |
| UI Framework | Next.js 14.2.30 + Tailwind CSS | Observability interface, `next dev` for Docker env var injection |
| UI Markdown | react-markdown 8.0.7 + remark-gfm 3.0.1 | Renders chunk_text as formatted Markdown. GFM plugin enables table rendering. |
| Container | Docker + docker-compose | Local = Production parity |
| HTTP Client | httpx | Phase 4.1 auto-process background task |

**Not using:** LangChain, LangGraph, batch orchestration (deferred to Harsh's production pipeline).

**Model IDs:**
```python
EMBEDDING_MODEL = "models/gemini-embedding-001"
VISION_MODEL = "gemini-2.0-flash"
```

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
| File | Description | Extraction Path | UI fidelity badge |
|---|---|---|---|
| CustomerChurn_Jan2025.xlsx | Native Excel, 15 customers, 10 cols | openpyxl → Markdown table | ≡ Full fidelity |
| PureTable_CustomerChurn_Jan2025.pdf | Same data as embedded PDF table | pdfplumber lines → Markdown table | ≡ Full fidelity |
| SS_CustomerChurn_Jan2025.pdf | Same data as screenshot (image PDF) | Gemini Vision description | ▣ Vision description |

The UI Comparison View auto-detects these as a group (base name `customerchurn_jan2025`
after stripping `PureTable_` / `SS_` prefixes) and shows them side-by-side.
All three produce 768-dim embeddings. Search quality is comparable — the screenshot
path produces a text description that contains all column names and key values.

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
  "chunk_text":      str,   # Raw text, Markdown table, or caption + Gemini Vision description
  "gcs_image_path":  str,   # "gs://rag-fl-documents/{doc_id}.{page_number}"      (first visual)
                            # "gs://rag-fl-documents/{doc_id}.{page_number}.v1"   (second)
                            # "gs://rag-fl-documents/{doc_id}.{page_number}.vN"   (Nth)
                            # None for text and table chunks

  # Embedding
  "embedding":           list[float],  # 768 dims, gemini-embedding-001
  "embedding_model":     str,          # "models/gemini-embedding-001"
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

## Per-Page Classification Logic (classifier.py)

Zero Gemini API cost at classification stage.

```
FORCE_MIXED_MODE=true  (env var, default: false)
→ Skip all detection, mark ALL pages as "mixed"
→ Every page gets Gemini Vision + text embedding (high API cost)
→ Use only for quick local tests

FORCE_MIXED_MODE=false (default — use always)
→ Run full 4-step element detection below

╔══════════════════════════════════════════════════════════════════════╗
║  STEP 1 — TABLE DETECTION  (3 strategies + validation)              ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Strategy 1 — pdfplumber LINES (Phase 3A)                           ║
║    find_tables(vertical=lines, horizontal=lines)                     ║
║    → lines_table_rects[]   reliable, can suppress visuals            ║
║                                                                      ║
║  Strategy 2 — whitespace word alignment (Phase 3B)                  ║
║    extract_words(x_tolerance=3)                                      ║
║    x0 cluster with 30pt gap → column centers                        ║
║    consecutive lines merged if gap <8pt AND same columns             ║
║    column consistency: each col appears in ≥40% of rows             ║
║    CID artifact filter: skip rows with "(cid:" in any cell           ║
║    → soft_table_rects[]    heuristic, never suppresses visuals       ║
║                                                                      ║
║  Strategy 3 — text+lines (Phase 3C, runs AFTER visual detect)       ║
║    find_tables(vertical=text, horizontal=lines)                      ║
║    catches horizontal-separator-only tables (no column borders)      ║
║    skips any bbox overlapping a visual element (>40%)                ║
║    → soft_table_rects[]                                              ║
║                                                                      ║
║  Validation (all strategies):                                        ║
║    non_empty cells ≥ 4  ·  not 1×1  ·  not all-prose (>80c/cell)   ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  STEP 2 — VISUAL DETECTION  (Phase 3D — REWRITTEN 2026-03-10)       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Step 2A — IMAGE XOBJECTS (no clustering, each separate)            ║
║    get_images(full=True) → raster images + XObject references       ║
║    Filter: area >= 0.5% of page (_MIN_IMAGE_AREA_RATIO)             ║
║    Filter: not >70% inside lines_table_rects                         ║
║    → Each XObject becomes SEPARATE visual element                    ║
║    (prevents merging distinct images like pivot tables + charts)     ║
║                                                                      ║
║  Step 2B — VECTOR DRAWINGS (gap-cluster + dedupe against images)    ║
║    get_drawings() → vector elements (axes, bars, pies)              ║
║    _cluster_rects(gap=20pt) → merge drawing paths into chart regions║
║    Filter: area >= 3% of page (_MIN_VISUAL_AREA_RATIO)              ║
║    Dedupe: skip if cluster >70% covered by image XObject            ║
║    → Prevents double-detection (chart drawing inside image bbox)     ║
║                                                                      ║
║  Step 2B' — PIXEL FALLBACK (when covered_area <50% of page)         ║
║    Renders 0.25x grayscale thumbnail of full page                    ║
║    if non_white >20% (was 15%, Phase 3E fix)                        ║
║    AND exceeds covered_area by >10%                                  ║
║    AND text_ratio <0.5                                               ║
║    → add full-page visual element                                    ║
║    Catches: Form XObjects, screenshots, missed vector content        ║
║                                                                      ║
║  Architectural Change (Phase 3D):                                    ║
║    Before: combined pool → cluster → try_split_cluster               ║
║    After:  images separate | drawings cluster → dedupe               ║
║    Result: Each PDF image XObject preserved as individual element    ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  STEP 3 — TEXT BLOCK DETECTION  (Phase 3E — FIXED 2026-03-10)       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  get_text("blocks") → for each text block:                          ║
║    Filter: char_count > 20 (was 50, Phase 3E — captures subtitles)  ║
║    Exclude from text_elements list:                                  ║
║      - center_y inside any table/visual bbox                         ║
║      - overlap >50% with any table bbox                              ║
║      - overlap >30% with any visual bbox (caption rule)              ║
║                                                                      ║
║  Chunker exclude_rects logic (Phase 3E fix):                         ║
║    OLD (OR logic): skip if center inside OR overlap >40%             ║
║    NEW (AND logic): skip ONLY if center inside AND overlap >70%      ║
║    → Paragraphs near tables no longer excluded                       ║
║                                                                      ║
║  Pipeline exclude_bboxes (Phase 3E fix):                             ║
║    Include: LINES-strategy tables + all visuals                      ║
║    Exclude: soft tables (whitespace, text+lines)                     ║
║    → Soft table bboxes don't suppress neighboring text               ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  PAGE TYPE DERIVATION  (from element presence)                       ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  full_page_image (Phase 3F) → capture entire page (see below)       ║
║  visual + (table or text)   → mixed                                  ║
║  visual only                → multimodal                             ║
║  table + text               → mixed                                  ║
║  table only                 → table                                  ║
║  text only                  → text                                   ║
║  nothing detected           → skip                                   ║
║                                                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  PHASE 3F — FULL-PAGE-AS-IMAGE  (2026-03-10)                        ║
╠══════════════════════════════════════════════════════════════════════╣
║                                                                      ║
║  Harsh's Directive (from meeting 2026-03-10):                        ║
║    "Wherever there is a table and image, just take the whole page    ║
║     as an image and embed it. When we are asking the question, we    ║
║     will retrieve the page and pass the same page in the context     ║
║     also. So that LLM will have the full understanding."             ║
║                                                                      ║
║  Trigger Conditions:                                                 ║
║    IF (has_table AND has_visual) OR complex_mixed_content            ║
║    → page_type = "full_page_image"                                   ║
║                                                                      ║
║  Processing:                                                         ║
║    1. classifier.py: set page_type="full_page_image"                 ║
║       detected_elements = [{"type":"full_page_image","bbox":full}]   ║
║                                                                      ║
║    2. chunker.py: chunk_full_page_image()                            ║
║       - Render FULL PAGE at 3x zoom (high quality)                   ║
║       - Upload to GCS: {doc_id}.{page_number} (no .fullpage suffix)  ║
║       - Gemini Vision prompt: "Describe this entire page in detail.  ║
║         Include all text content, tables (with data), charts,        ║
║         diagrams, and their relationships."                          ║
║       - Return single ChunkRecord:                                   ║
║         * chunk_type = "multimodal"                                  ║
║         * chunk_text = comprehensive Gemini description              ║
║         * gcs_image_path = gs://bucket/{doc_id}.{page_number}        ║
║         * bounding_box = null (entire page)                          ║
║         * format_provenance.is_full_page = true                      ║
║                                                                      ║
║    3. pipeline.py: element dispatch                                  ║
║       IF element["type"] == "full_page_image":                       ║
║         chunks.append(chunk_full_page_image(...))                    ║
║         break  # skip other element processing for this page         ║
║                                                                      ║
║  Problem Solved:                                                     ║
║    Page 5 Titanic: table with invisible borders + bar chart          ║
║    Before: 3 fragmented chunks (table, chart, text) — hard to parse  ║
║    After:  1 holistic chunk (full page) — LLM sees complete context  ║
║                                                                      ║
║  Benefits:                                                           ║
║    - Simplifies complex layout parsing (invisible table borders)     ║
║    - LLM gets complete page context during retrieval                 ║
║    - Reduces edge cases (merged cells, nested tables, etc.)          ║
║    - Single Gemini call vs multiple element calls                    ║
║                                                                      ║
║  Example Output (MongoDB doc_embeddings):                            ║
║    chunk_type: "multimodal"                                          ║
║    chunk_text: "This page shows customer churn analysis with a       ║
║                 table listing 15 customers (ID, Name, Plan, Churn    ║
║                 Status, Reason) and a bar chart below visualizing    ║
║                 churn counts by subscription plan..."                ║
║    gcs_image_path: "gs://rag-fl-documents/{doc_id}.5"                ║
║    format_provenance.is_full_page: true                              ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

Non-PDF logical pages (classify_non_pdf):
  Excel sheet  → "table"          (pdfplumber table extract path)
  YAML file    → "structured_text"
  JPEG/PNG     → "multimodal"     (Gemini Vision path)
```

---

## Embedding Strategy — gemini-embedding-001

### Asymmetric Task Types — MANDATORY, NEVER MIX

```python
# Phase 3: storing chunks — ALWAYS RETRIEVAL_DOCUMENT
result = genai.embed_content(
    model="models/gemini-embedding-001",
    content=chunk_text,
    task_type="RETRIEVAL_DOCUMENT",
    output_dimensionality=768  # explicit 768-dim
)

# Phase 6: user query — ALWAYS RETRIEVAL_QUERY
result = genai.embed_content(
    model="models/gemini-embedding-001",
    content=user_query,
    task_type="RETRIEVAL_QUERY",
    output_dimensionality=768
)
```

**Using same task_type for both degrades retrieval quality significantly.** This is asymmetric by design.

**Model deviation note:** Originally specified `text-embedding-004`, but API key returned 404. Switched to `gemini-embedding-001` which produces identical 768-dim vectors with same task_type support. Zero code changes required for future migration back to text-embedding-004.

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
  └── flat-images/       ← Rendered visual crop PNGs before GCS upload
                            naming: {doc_id}_page_{page_number}.png
                                    {doc_id}_page_{page_number}.v1.png
                                    {doc_id}_page_{page_number}.v2.png  ...

GCS bucket:  rag-fl-documents
GCS keys:
  Source file:           {doc_id}/{filename}
  First visual per page: {doc_id}.{page_number}          ← backward compat
  Second visual:         {doc_id}.{page_number}.v1
  Third visual:          {doc_id}.{page_number}.v2
  Nth visual:            {doc_id}.{page_number}.v{N-1}

  The .v{n} suffix is parsed by gcsImageUrl() in the UI to route
  GET /image/{doc_id}/{page}?v=N to the correct crop.
  v=0 (default, no param) → first crop; v=1 → second; v=N → Nth.
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