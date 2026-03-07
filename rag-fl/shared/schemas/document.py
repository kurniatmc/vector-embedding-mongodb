"""
shared/schemas/document.py
Pydantic model for the MongoDB `documents` collection.
Extended with deduplication + chronological metadata fields (ARCHITECTURE.md).
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class DocumentRecord(BaseModel):
    # ── Identity ────────────────────────────────────────────────────────────
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    original_format: str          # "pdf" | "xlsx" | "yaml" | "jpeg" | "png" | "pptx" | "docx"
    gcs_path: str                 # e.g. "{doc_id}/{filename}"

    # ── Processing state ─────────────────────────────────────────────────────
    total_pages: int
    status: str = "UPLOADED"      # UPLOADED | PROCESSING | EMBEDDED | FAILED
    source_channel: str = "manual_upload"  # manual_upload | folder_watcher | onedrive
    format_provenance: dict       # processor.extract_provenance() output

    # ── Deduplication ────────────────────────────────────────────────────────
    content_hash: str             # sha256(file_bytes) — always computed at ingest
    is_duplicate_of: Optional[str] = None  # doc_id of original if duplicate, else None

    # ── Chronological Metadata ───────────────────────────────────────────────
    report_series: Optional[str] = None   # "monthly_churn" | user-defined | None
    report_period: Optional[str] = None   # "2025-01" | "2025-Q1" | None
    report_period_start: Optional[datetime] = None
    report_period_end: Optional[datetime] = None
    report_frequency: Optional[str] = None  # "monthly" | "quarterly" | "annual" | "ad-hoc" | None
    period_confidence: str = "none"         # "high" | "medium" | "low" | "none"
    extraction_method: str = "none"         # "filename" | "pdf_metadata" | "first_page_text" | "none"

    # ── Upload Audit ─────────────────────────────────────────────────────────
    upload_timestamp: datetime = Field(default_factory=datetime.utcnow)
    uploaded_by: Optional[str] = None  # email/user from request header, or None

    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_mongo(self) -> dict:
        d = self.model_dump()
        d["_id"] = d.pop("doc_id")
        return d
