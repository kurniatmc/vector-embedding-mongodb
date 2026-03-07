# Phase 2 — Format Registry & Ingestion Service
## Claude Code Prompt (Copy-Paste Ready)

> **Status:** ✅ Complete — this file is kept for reference only.
> Phase 2 is done and tested with all 5 sample docs.
> **Schema update required:** see section "Schema Extension After Sync on Embedding Meeting" below.

---

## Schema Extension After "Sync on Embedding" Meeting

Phase 2's `documents{}` schema must be extended with chronological metadata and deduplication fields.
These were added based on Harsh's requirement about recurring monthly reports.

**Update `shared/schemas/document.py`** to add:

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import hashlib

class DocumentRecord(BaseModel):
    # Original Phase 2 fields
    doc_id: str
    filename: str
    original_format: str
    gcs_path: str
    total_pages: int
    status: str                         # UPLOADED | PROCESSING | EMBEDDED | FAILED
    source_channel: str                 # manual_upload | folder_watcher | onedrive
    format_provenance: dict
    created_at: datetime
    updated_at: datetime

    # ── NEW: Deduplication ─────────────────────────────────────────────────────
    content_hash: str                   # sha256(file_bytes) — always computed
    is_duplicate_of: Optional[str]      # doc_id of original if duplicate, else None

    # ── NEW: Chronological Metadata ────────────────────────────────────────────
    report_series: Optional[str]        # "monthly_churn" | user-defined | None
    report_period: Optional[str]        # "2025-01" | "2025-Q1" | None
    report_period_start: Optional[datetime]
    report_period_end: Optional[datetime]
    report_frequency: Optional[str]     # "monthly" | "quarterly" | "annual" | "ad-hoc" | None
    period_confidence: str              # "high" | "medium" | "low" | "none"
    extraction_method: str              # "filename" | "pdf_metadata" | "first_page_text" | "none"

    # ── NEW: Upload Audit ──────────────────────────────────────────────────────
    upload_timestamp: datetime          # UTC timestamp of upload
    uploaded_by: Optional[str]          # Email/user from request header or None
```

**Update ingestion `services/ingestion/app/main.py`** to populate these fields at ingest:

```python
import hashlib
import re
from datetime import datetime

def compute_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def check_duplicate(mongo_client, content_hash: str) -> Optional[str]:
    """Returns existing doc_id if hash already exists, else None."""
    existing = mongo_client.documents.find_one({"content_hash": content_hash})
    return existing["doc_id"] if existing else None

def extract_report_period(filename: str, file_bytes: bytes, mime_type: str) -> dict:
    """Best-effort extraction of report period. Returns dict of chrono metadata fields."""
    result = {
        "report_period": None,
        "report_period_start": None,
        "report_period_end": None,
        "period_confidence": "none",
        "extraction_method": "none",
        "report_frequency": None,
        "report_series": None
    }

    # Strategy 1: Filename patterns
    filename_lower = filename.lower()
    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12"
    }

    # Pattern: "January_2025" or "Jan2025" or "2025-01" or "2025_01"
    for month_name, month_num in month_map.items():
        year_pattern = rf"{month_name}[_\-\s]?(\d{{4}})|(\d{{4}})[_\-\s]?{month_name}"
        match = re.search(year_pattern, filename_lower)
        if match:
            year = match.group(1) or match.group(2)
            result["report_period"] = f"{year}-{month_num}"
            result["period_confidence"] = "high"
            result["extraction_method"] = "filename"
            result["report_frequency"] = "monthly"
            break

    # Pattern: "Q1_2025" or "2025-Q1"
    if not result["report_period"]:
        q_match = re.search(r"q([1-4])[_\-]?(\d{4})|(\d{4})[_\-]?q([1-4])", filename_lower)
        if q_match:
            quarter = q_match.group(1) or q_match.group(4)
            year = q_match.group(2) or q_match.group(3)
            result["report_period"] = f"{year}-Q{quarter}"
            result["period_confidence"] = "high"
            result["extraction_method"] = "filename"
            result["report_frequency"] = "quarterly"

    # Strategy 2: PDF metadata (if PDF)
    if not result["report_period"] and "pdf" in mime_type:
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            meta = doc.metadata
            creation = meta.get("creationDate", "") or meta.get("modDate", "")
            # PDF date format: D:20250115120000+00'00'
            date_match = re.search(r"D:(\d{4})(\d{2})", creation)
            if date_match:
                result["report_period"] = f"{date_match.group(1)}-{date_match.group(2)}"
                result["period_confidence"] = "medium"
                result["extraction_method"] = "pdf_metadata"
        except Exception:
            pass

    # Strategy 3: First-page text scan (PDF only)
    if not result["report_period"] and "pdf" in mime_type:
        try:
            import fitz
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            first_page_text = doc[0].get_text()[:500]
            for month_name, month_num in month_map.items():
                match = re.search(
                    rf"{month_name}[_\-\s]?(\d{{4}})|(\d{{4}})[_\-\s]?{month_name}",
                    first_page_text.lower()
                )
                if match:
                    year = match.group(1) or match.group(2)
                    result["report_period"] = f"{year}-{month_num}"
                    result["period_confidence"] = "medium"
                    result["extraction_method"] = "first_page_text"
                    result["report_frequency"] = "monthly"
                    break
        except Exception:
            pass

    return result
```

---

## Original Phase 2 Prompt (Complete — For Reference)

```
Read ARCHITECTURE.md, PHASES.md completely before starting.

--- CURRENT STATE ---
Phase 1 (Docker Infrastructure) is complete and running.
[paste output of: docker ps]
[paste output of: make test-infra]

--- PHASE 2 GOAL ---
Build the Format Registry & Ingestion Service.

This service is the entry point for ALL files into the system.
It must be format-agnostic — not a "PDF service that also handles Excel",
but a registry-driven system where adding a new format = adding one new Processor class.

--- DIRECTORY STRUCTURE TO CREATE ---

services/ingestion/
├── app/
│   ├── main.py                  ← FastAPI app, routes
│   ├── registry.py              ← FormatRegistry class
│   ├── processors/
│   │   ├── base.py              ← BaseProcessor abstract class
│   │   ├── pdf_processor.py
│   │   ├── excel_processor.py
│   │   ├── pptx_processor.py    ← delegates to Gotenberg then PDFProcessor
│   │   ├── docx_processor.py    ← delegates to Gotenberg then PDFProcessor
│   │   ├── yaml_processor.py
│   │   └── image_processor.py   ← handles JPEG + PNG
│   ├── watcher.py               ← folder watcher for /input (dev mode)
│   └── webhooks.py              ← OneDrive webhook endpoint
├── Dockerfile
└── requirements.txt

--- INGESTION FLOW ---

POST /ingest (multipart/form-data, field: file)

1. Receive file bytes + filename
2. Detect MIME type (python-magic)
3. compute content_hash = sha256(file_bytes)
4. Check MongoDB: if content_hash exists → return {status: "duplicate", doc_id: existing_doc_id}
5. Get processor from registry
6. processor.validate() → raise 400 if invalid
7. If dry_run=true → return DryRunResponse without saving
8. processor.normalize() → NormalizedOutput
9. Generate doc_id (UUID)
10. Save to GCS: {doc_id}/{filename}
11. Extract report_period metadata (see extract_report_period function above)
12. Save to MongoDB documents{} with ALL fields including chrono metadata
13. Return IngestResponse: {doc_id, filename, format, pages, gcs_path, status, report_period}

--- TESTING SEQUENCE ---

1. PDF ingestion:
curl.exe -X POST http://localhost:8001/ingest -F "file=@tests/sample-docs/Churn_EDA_Report.pdf"
Expected: {doc_id, status: "UPLOADED", content_hash: "<sha256>", report_period: null}

2. Excel ingestion:
curl.exe -X POST http://localhost:8001/ingest -F "file=@tests/sample-docs/Apartment_Specialists_Churn_Jan2025.xlsx"
Expected: {report_period: "2025-01", period_confidence: "high", extraction_method: "filename"}

3. Deduplication test:
Upload same file twice → second response: {status: "duplicate", doc_id: "<original_id>"}
Verify: db.documents.countDocuments({filename: "Churn_EDA_Report.pdf"}) === 1

4. Verify all fields in MongoDB:
db.documents.findOne({}, {content_hash:1, report_period:1, period_confidence:1, upload_timestamp:1})

5. All 5 sample docs ingested successfully.
```

---

## Troubleshooting

**Gotenberg/LibreOffice not converting:**
```bash
docker compose logs libreoffice
curl http://localhost:3000/health
```

**fake-gcs authentication error:**
```bash
# GCS_ENDPOINT=http://fake-gcs:4443 must be set
# AnonymousCredentials required for fake-gcs
```

**MIME detection wrong:**
```bash
# Dockerfile must have: RUN apt-get install -y libmagic1
```

**MongoDB connection from ingestion service:**
```bash
# Use internal Docker network: mongo (not localhost)
# MONGODB_URI=mongodb://mongo:27017/ragfl?replicaSet=rs0
```
