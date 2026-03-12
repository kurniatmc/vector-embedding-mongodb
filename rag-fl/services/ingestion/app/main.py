"""
services/ingestion/app/main.py
FastAPI ingestion service — entry point for all files into the rag-fl pipeline.
Port: 8001 (INGESTION_PORT)
"""
import hashlib
import logging
import os
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import BackgroundTasks, FastAPI, File, UploadFile, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .registry import get_processor, UnsupportedFormatError
from .webhooks import router as webhooks_router
from .watcher import start_watcher

from shared.utils.gcs_client import upload_bytes
from shared.utils.mongo_client import documents as get_documents_collection
from shared.utils.period_extractor import extract_report_period

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ingestion.main")


# ── Response models ───────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    original_format: str
    total_pages: int
    gcs_path: str
    status: str
    source_channel: str
    content_hash: str
    report_period: Optional[str] = None
    period_confidence: str = "none"
    is_duplicate_of: Optional[str] = None


class DuplicateResponse(BaseModel):
    status: str = "duplicate"
    doc_id: str                   # existing original doc_id
    content_hash: str
    message: str


class DryRunResponse(BaseModel):
    filename: str
    format: str
    estimated_pages: int
    estimated_multimodal_pages: int
    estimated_gemini_vision_calls: int
    estimated_text_chunks: int
    would_save_to_gcs: str
    would_create_doc_id: str
    message: str = "DRY RUN — nothing was saved"


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_watcher()
    yield


app = FastAPI(
    title="rag-fl Ingestion Service",
    version="2.1.0",
    description="Format-agnostic file intake. Handles PDF, Excel, PPTX, DOCX, YAML, JPEG, PNG.",
    lifespan=lifespan,
)
# CORS_ORIGINS can be comma-separated list for production
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(webhooks_router)


# ── Background pipeline trigger ───────────────────────────────────────────────

PIPELINE_URL = os.getenv("PIPELINE_URL", "http://rag-fl:8004")

async def trigger_pipeline_processing(doc_id: str) -> None:
    """
    Call rag-fl /process with processing_method='both' to run PyMuPDF + MarkItDown.
    On failure, rollback the document from MongoDB.
    """
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(
                f"{PIPELINE_URL}/process",
                json={"doc_id": doc_id, "dry_run": False, "processing_method": "both"},
            )
            resp.raise_for_status()
            logger.info(f"Auto-process succeeded for doc_id={doc_id}")
    except Exception as e:
        logger.error(f"Auto-process failed for doc_id={doc_id}: {e} — rolling back")
        db = get_documents_collection().database
        db.documents.delete_one({"doc_id": doc_id})
        db.page_profiles.delete_many({"doc_id": doc_id})
        db.doc_embeddings.delete_many({"doc_id": doc_id})


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "up", "service": "ingestion"}


# ── Ingest endpoint ───────────────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="If true, return estimates without saving anything"),
    source_channel: str = Query("manual_upload", description="manual_upload | folder_watcher | onedrive"),
    x_uploaded_by: Optional[str] = Header(None, description="Email/user identity for audit"),
):
    filename = file.filename or "unknown"
    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    # 1. Compute content hash immediately (always)
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # 2. Get processor from registry
    try:
        processor, mime_type = get_processor(file_bytes, filename)
    except UnsupportedFormatError as e:
        raise HTTPException(status_code=415, detail=str(e))

    # 3. Validate
    if not processor.validate(file_bytes):
        raise HTTPException(status_code=400, detail=f"File validation failed for {filename}")

    # 4. Normalize (may call Gotenberg for PPTX/DOCX)
    try:
        normalized = processor.normalize(file_bytes, filename)
    except Exception as e:
        logger.error(f"Normalization failed for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Normalization failed: {e}")

    format_provenance = processor.extract_provenance(normalized)
    original_format = format_provenance.get("original_format", mime_type.split("/")[-1])

    # 5. Dry run — return estimates, touch nothing
    if dry_run:
        would_doc_id = str(uuid.uuid4())
        gcs_bucket = os.getenv("GCS_BUCKET", "rag-fl-documents")
        would_gcs_path = f"{would_doc_id}/{filename}"
        est_multimodal = max(1, normalized.page_count // 4)
        est_text_chunks = normalized.page_count * 3
        logger.info(f"DRY RUN: {filename} → {normalized.page_count} pages, format={original_format}")
        return DryRunResponse(
            filename=filename,
            format=original_format,
            estimated_pages=normalized.page_count,
            estimated_multimodal_pages=est_multimodal,
            estimated_gemini_vision_calls=est_multimodal,
            estimated_text_chunks=est_text_chunks,
            would_save_to_gcs=f"gs://{gcs_bucket}/{would_gcs_path}",
            would_create_doc_id=would_doc_id,
        )

    # 6. Deduplication check
    existing = get_documents_collection().find_one({"content_hash": content_hash}, {"doc_id": 1})
    if existing:
        existing_doc_id = existing["doc_id"]
        logger.info(f"Duplicate detected: {filename} → existing doc_id={existing_doc_id}")
        return DuplicateResponse(
            status="duplicate",
            doc_id=existing_doc_id,
            content_hash=content_hash,
            message=f"File already ingested as doc_id={existing_doc_id}. Skipping re-embedding.",
        )

    # 7. Generate doc_id and GCS path
    doc_id = str(uuid.uuid4())
    gcs_path = f"{doc_id}/{filename}"

    # 8. Upload to GCS
    # DOCX/PPTX: the pipeline expects PDF bytes (Gotenberg-converted).
    #   - Primary path → normalized PDF bytes (for PyMuPDF/pdfplumber pipeline)
    #   - Secondary path → original DOCX/PPTX bytes (for MarkItDown native extraction)
    # All other formats: upload original bytes as-is.
    gcs_original_path: Optional[str] = None
    upload_content = file_bytes
    upload_content_type = mime_type

    if original_format in ("docx", "pptx"):
        upload_content = normalized.file_bytes   # Gotenberg-converted PDF
        upload_content_type = "application/pdf"
        orig_path = f"{doc_id}/orig_{filename}"
        try:
            upload_bytes(file_bytes, orig_path, content_type=mime_type)
            gcs_original_path = orig_path
            logger.info(f"Stored original {original_format} at GCS:{orig_path} (for MarkItDown)")
        except Exception as e:
            logger.warning(f"Could not store original bytes for MarkItDown ({filename}): {e}")

    try:
        gcs_uri = upload_bytes(upload_content, gcs_path, content_type=upload_content_type)
        logger.info(f"Uploaded {filename} to GCS: {gcs_uri}")
    except Exception as e:
        logger.error(f"GCS upload failed for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"GCS upload failed: {e}")

    # 9. Extract chronological metadata
    chrono = extract_report_period(filename, file_bytes, mime_type)

    # 10. Save to MongoDB documents collection
    now = datetime.utcnow()
    doc_record = {
        "_id": doc_id,
        "doc_id": doc_id,
        "filename": filename,
        "original_format": original_format,
        "gcs_path": gcs_path,
        "total_pages": normalized.page_count,
        "status": "UPLOADED",
        "source_channel": source_channel,
        "format_provenance": format_provenance,
        # Deduplication
        "content_hash": content_hash,
        "is_duplicate_of": None,
        # Secondary GCS path for original DOCX/PPTX bytes (MarkItDown native extraction)
        "gcs_original_path": gcs_original_path,
        # Chronological metadata
        "report_series": chrono.get("report_series"),
        "report_period": chrono.get("report_period"),
        "report_period_start": chrono.get("report_period_start"),
        "report_period_end": chrono.get("report_period_end"),
        "report_frequency": chrono.get("report_frequency"),
        "period_confidence": chrono.get("period_confidence", "none"),
        "extraction_method": chrono.get("extraction_method", "none"),
        # Upload audit
        "upload_timestamp": now,
        "uploaded_by": x_uploaded_by,
        # Timestamps
        "created_at": now,
        "updated_at": now,
    }

    try:
        get_documents_collection().insert_one(doc_record)
        logger.info(
            f"Saved {filename} to MongoDB: doc_id={doc_id}, pages={normalized.page_count}, "
            f"report_period={chrono.get('report_period')}, confidence={chrono.get('period_confidence')}"
        )
    except Exception as e:
        logger.error(f"MongoDB insert failed for {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"MongoDB insert failed: {e}")

    # Auto-trigger pipeline processing in background
    background_tasks.add_task(trigger_pipeline_processing, doc_id)
    logger.info(f"Queued auto-process for doc_id={doc_id}")

    return IngestResponse(
        doc_id=doc_id,
        filename=filename,
        original_format=original_format,
        total_pages=normalized.page_count,
        gcs_path=gcs_path,
        status="UPLOADED",
        source_channel=source_channel,
        content_hash=content_hash,
        report_period=chrono.get("report_period"),
        period_confidence=chrono.get("period_confidence", "none"),
        is_duplicate_of=None,
    )


# ── Document query helpers ────────────────────────────────────────────────────

@app.get("/documents")
async def list_documents(limit: int = Query(20), skip: int = Query(0)):
    docs = list(
        get_documents_collection()
        .find({}, {"_id": 0, "doc_id": 1, "filename": 1, "original_format": 1,
                   "total_pages": 1, "status": 1, "report_period": 1, "created_at": 1})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    for d in docs:
        if "created_at" in d:
            d["created_at"] = d["created_at"].isoformat()
    return {"documents": docs, "count": len(docs)}


@app.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = get_documents_collection().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    for ts_field in ("created_at", "updated_at", "upload_timestamp"):
        if ts_field in doc and doc[ts_field]:
            doc[ts_field] = doc[ts_field].isoformat()
    return doc
