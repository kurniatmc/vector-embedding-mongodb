# Phase 2 Summary
> Auto-generated at end of phase. Save to docs/phase_summaries/phase_2_summary.md

---

## Phase 2 — Format Registry & Ingestion Service
**Completed:** 2026-03-05
**Status:** ✅ Complete

---

## 1. Files Created

| File | Description |
|---|---|
| `services/ingestion/app/main.py` | FastAPI app — `/ingest`, `/documents`, `/health` endpoints |
| `services/ingestion/app/registry.py` | `FormatRegistry`: MIME → Processor, python-magic detection, extension fallback |
| `services/ingestion/app/processors/base.py` | `BaseProcessor` abstract class + `NormalizedOutput` dataclass |
| `services/ingestion/app/processors/pdf_processor.py` | PDF: PyMuPDF, page count, metadata |
| `services/ingestion/app/processors/excel_processor.py` | Excel: openpyxl, sheet → logical page |
| `services/ingestion/app/processors/yaml_processor.py` | YAML: PyYAML, top-level keys |
| `services/ingestion/app/processors/image_processor.py` | JPEG/PNG: Pillow, dimensions |
| `services/ingestion/app/processors/pptx_processor.py` | PPTX: slide count via python-pptx → Gotenberg → PDFProcessor |
| `services/ingestion/app/processors/docx_processor.py` | DOCX: Gotenberg conversion → PDFProcessor |
| `services/ingestion/app/watcher.py` | watchdog folder watcher on `/input`, dev mode only |
| `services/ingestion/app/webhooks.py` | OneDrive webhook stub — logs payload, returns 200 |
| `services/ingestion/Dockerfile` | python:3.11-slim + libmagic1 + curl, build context = project root |
| `services/ingestion/requirements.txt` | All Python dependencies |
| `shared/schemas/__init__.py` | Package marker |
| `shared/schemas/chunk.py` | `ChunkRecord` Pydantic model — Canonical Chunk Schema |
| `shared/schemas/document.py` | `DocumentRecord` Pydantic model — documents collection |
| `shared/schemas/page_profile.py` | `PageProfile` Pydantic model — page_profiles collection (Phase 4) |
| `shared/utils/gcs_client.py` | `upload_bytes`, `download_bytes` — AnonymousCredentials for fake-gcs |
| `shared/utils/mongo_client.py` | `get_db()`, collection accessors: `documents()`, `page_profiles()`, etc. |

---

## 2. How to Verify

```bash
# Health check
curl http://localhost:8001/health
# Expected: {"status":"up","service":"ingestion"}

# Ingest a PDF
curl -X POST http://localhost:8001/ingest \
  -F "file=@tests/sample-docs/Churn_EDA_Report.pdf"
# Expected: {doc_id, filename, original_format:"pdf", total_pages:9, status:"UPLOADED"}

# Dry run — no DB writes
curl -X POST "http://localhost:8001/ingest?dry_run=true" \
  -F "file=@tests/sample-docs/Titanic_data_pdf_1.pdf"
# Expected: DryRunResponse with estimated_pages:11, message:"DRY RUN — nothing was saved"

# MongoDB: confirm documents
docker compose exec mongo mongosh --quiet \
  --eval "db.documents.find({},{filename:1,total_pages:1,status:1,_id:0}).toArray().forEach(d=>print(JSON.stringify(d)))" ragfl

# GCS: list uploaded objects
curl -s "http://localhost:4443/storage/v1/b/rag-fl-documents/o" | \
  python3 -c "import sys,json; [print(i['name']) for i in json.load(sys.stdin).get('items',[])]"

# List all documents via API
curl -s http://localhost:8001/documents | python3 -m json.tool
```

---

## 3. Test Results

| Test | Input | Expected | Actual | Pass? |
|---|---|---|---|---|
| PDF ingest | `Churn_EDA_Report.pdf` | `total_pages=9, status=UPLOADED` | `total_pages=9, status=UPLOADED` | ✅ |
| PDF ingest | `Titanic_data_pdf_1.pdf` | `total_pages=11, status=UPLOADED` | `total_pages=11, status=UPLOADED` | ✅ |
| PDF ingest | `Machine Learning in Detecting Fraud Literature Review.pdf` | `total_pages=13, status=UPLOADED` | `total_pages=13, status=UPLOADED` | ✅ |
| PDF ingest | `guidelines_part_01_pages_1-15.pdf` | `total_pages=15, status=UPLOADED` | `total_pages=15, status=UPLOADED` | ✅ |
| PDF ingest | `guidelines_part_02_pages_16-30.pdf` | `total_pages=15, status=UPLOADED` | `total_pages=15, status=UPLOADED` | ✅ |
| MongoDB count | after 5 ingestions | `5` | `5` | ✅ |
| GCS objects | after 5 ingestions | 5 objects at `{doc_id}/{filename}` | 5 objects present | ✅ |
| Provenance | `Churn_EDA_Report.pdf` | `format_provenance.original_format=pdf, page_count=9` | Both correct | ✅ |
| Dry run | `Titanic_data_pdf_1.pdf` + `?dry_run=true` | `DryRunResponse`, no MongoDB record | DryRunResponse returned, count still 5 | ✅ |
| /health | GET `/health` | `{"status":"up"}` | `{"status":"up","service":"ingestion"}` | ✅ |

---

## 4. Gemini API Usage

Not applicable — Phase 2 is ingestion only. No Gemini Vision or embedding calls.

---

## 5. Deviations from ARCHITECTURE.md

| Decision | ARCHITECTURE.md says | What was implemented | Reason |
|---|---|---|---|
| MIME detection fallback | Not specified | Extension fallback when libmagic returns `application/octet-stream` or `application/zip` | ZIP-based formats (XLSX, PPTX, DOCX) are detected as generic ZIP by libmagic; extension fallback gives correct MIME type |
| `text/plain` → YAMLProcessor | Not in REGISTRY | Added `"text/plain": YAMLProcessor` | libmagic sometimes detects plain YAML files as `text/plain` on some systems |
| Build context | Not specified | Project root (`.`) with `dockerfile: services/ingestion/Dockerfile` | Single build context needed to include both `shared/` and `services/ingestion/` in Docker layer |
| GCS path format | `{doc_id}.{page_number}` for page images | `{doc_id}/{filename}` for whole documents at ingest | Per-page GCS paths (`{doc_id}.{page_num}`) are for Phase 5 rendered PNGs; Phase 2 stores the original file |

---

## 6. Known Limitations / TODOs

- [ ] OneDrive webhook is a stub — only logs and returns 200. Real download from Graph API deferred to Phase 3+.
- [ ] Folder watcher ingest URL is hardcoded to `http://localhost:8001/ingest` — works when watcher runs inside the container (same process). Uses httpx for internal call.
- [ ] Dry run `estimated_multimodal_pages` and `estimated_text_chunks` are rough heuristics (1/4 of pages = multimodal, 3 chunks/page). Phase 4 page_profiles will give exact values.
- [x] ~~Duplicate file uploads are allowed~~ → **UPDATED Phase 3:** Content-hash deduplication implemented via SHA-256. Duplicate files return `is_duplicate: true`.
- [x] **UPDATED Phase 4.1:** Auto-process after upload implemented. Background task triggers pipeline processing automatically; rollback on failure. See `phase_4.1_workflow_improvements.md`.
- [ ] `text/plain` → YAML fallback could misroute actual text files if extension is not present.

---

## 7. Prerequisites for Phase 3

Before starting Phase 3 (File Ledger & Batch Orchestration), verify:

- [ ] `docker compose ps` → `ragfl-ingestion` shows `(healthy)`
- [ ] `curl http://localhost:8001/health` returns `{"status":"up",...}`
- [ ] All 5 sample PDFs in `documents` collection with `status=UPLOADED`
- [ ] Each document has `gcs_path`, `format_provenance`, `total_pages` populated
- [ ] `ragfl-redis` is healthy (Phase 3 will use it for the queue)

```bash
# Run this to confirm ready for Phase 3:
docker compose exec mongo mongosh --quiet \
  --eval "db.documents.find({status:'UPLOADED'},{filename:1,total_pages:1,_id:0}).toArray().forEach(d=>print(JSON.stringify(d)))" ragfl
# Must show all 5 docs with correct page counts
```
