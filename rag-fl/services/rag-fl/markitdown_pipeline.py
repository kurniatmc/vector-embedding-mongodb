"""
services/rag-fl/markitdown_pipeline.py
MarkItDown-based embedding pipeline — runs in parallel with PyMuPDF method for comparison.

Key design:
  - Chunks tagged processing_method='markitdown' in doc_embeddings
  - Does NOT change document status (EMBEDDED is set by PyMuPDF pipeline)
  - Does NOT touch pymupdf chunks — completely isolated
  - Re-runnable: deletes old markitdown chunks for the doc_id before re-storing

This file is intentionally self-contained so the comparison can be disabled or
swapped out without touching any existing pipeline code.
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

if not os.path.exists("/.dockerenv"):
    os.environ["MONGODB_URI"] = "mongodb://localhost:27017/ragfl?directConnection=true"
    os.environ["GCS_ENDPOINT"] = "http://localhost:4443"

from shared.schemas.chunk import ChunkRecord  # noqa: E402
from shared.utils.mongo_client import (  # noqa: E402
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
)
from embedder import embed_texts  # noqa: E402
from markitdown_extractor import extract_with_markitdown  # noqa: E402

logger = logging.getLogger("ragfl.markitdown_pipeline")

# ── Processing guards ──────────────────────────────────────────────────────────

# Baseline files are reserved for FORMAT comparison (different variants of same data).
# They must NOT receive MarkItDown processing — their "existing" chunks are the baseline.
BASELINE_FILENAMES: set[str] = {
    "CustomerChurn_Jan2025.xlsx",
    "PureTable_CustomerChurn_Jan2025.pdf",
    "SS_CustomerChurn_Jan2025.pdf",
}

# Formats that are OPTIMAL with their existing pipelines — MarkItDown adds no value.
_BLOCKED_FORMATS: set[str] = {"pdf", "jpeg", "jpg", "png", "gif", "bmp", "tiff"}

# Formats where MarkItDown is the comparison candidate.
_SUPPORTED_FORMATS: set[str] = {"xlsx", "xls", "docx", "pptx", "csv", "yaml", "yml"}


def should_process_with_markitdown(filename: str, original_format: str) -> bool:
    """
    Guard: returns True only when MarkItDown comparison is appropriate.

    Rules:
    - Baseline files → False (format comparison only, never method comparison)
    - PDF files → False (PyMuPDF + Gemini Vision is optimal, do not compare)
    - Image files → False (Gemini Vision is optimal, do not compare)
    - Office files (xlsx, xls, docx, pptx, csv) → True
    - YAML → True
    """
    if filename in BASELINE_FILENAMES:
        logger.info(f"MarkItDown blocked — baseline file: {filename}")
        return False
    if original_format in _BLOCKED_FORMATS:
        logger.info(f"MarkItDown blocked — format {original_format}: {filename}")
        return False
    if original_format in _SUPPORTED_FORMATS:
        return True
    logger.warning(f"MarkItDown skipped — unrecognized format '{original_format}': {filename}")
    return False


def run_markitdown_pipeline(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    original_format: str,
    format_provenance: dict,
) -> dict:
    """
    Extract → chunk → embed → store using MarkItDown.
    Chunks are tagged processing_method='markitdown'.
    """
    logger.info(f"=== MarkItDown pipeline: {filename} | doc_id={doc_id} ===")

    sections = extract_with_markitdown(file_bytes, filename, original_format)
    logger.info(f"MarkItDown: {len(sections)} sections extracted from {filename}")

    if not sections:
        logger.warning(f"MarkItDown produced no sections for {filename} — skipping storage")
        return {"doc_id": doc_id, "filename": filename, "total_chunks": 0, "method": "markitdown"}

    all_chunks: list[ChunkRecord] = []
    for i, section in enumerate(sections):
        content = (section.get("content") or "").strip()
        if not content:
            continue

        # Build rich provenance for comparison metadata display
        prov: dict = {"original_format": original_format, "extraction": "markitdown"}
        heading = section.get("heading", "")
        if original_format in ("xlsx", "xls") and heading:
            prov["sheet_name"] = heading
        elif original_format == "pptx":
            prov["slide_number"] = section.get("page_number", i + 1)
            if heading:
                prov["section"] = heading
        elif original_format == "docx" and heading:
            prov["section"] = heading
        elif original_format == "pdf" and heading:
            prov["section"] = heading

        chunk = ChunkRecord(
            doc_id=doc_id,
            page_number=section.get("page_number", i + 1),
            section_title=heading,
            chunk_index=i,
            chunk_type="table" if section.get("is_table") else "text",
            chunk_text=content,
            processing_method="markitdown",
            format_provenance=prov,
        )
        all_chunks.append(chunk)

    if not all_chunks:
        return {"doc_id": doc_id, "filename": filename, "total_chunks": 0, "method": "markitdown"}

    # Batch embed
    _embedding_model = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    logger.info(f"Embedding {len(all_chunks)} MarkItDown chunks via {_embedding_model} ...")
    texts = [c.chunk_text for c in all_chunks]
    embeddings = embed_texts(texts)
    for chunk, emb in zip(all_chunks, embeddings):
        chunk.embedding = emb
        chunk.embedding_model = _embedding_model
        chunk.embedding_task_type = "RETRIEVAL_DOCUMENT"

    # Replace existing markitdown chunks (idempotent re-run)
    embeddings_col = get_embeddings_col()
    embeddings_col.delete_many({"doc_id": doc_id, "processing_method": "markitdown"})

    stored = 0
    for chunk in all_chunks:
        embeddings_col.insert_one(chunk.to_mongo())
        stored += 1

    logger.info(f"=== MarkItDown pipeline complete: {stored} chunks stored | {doc_id} ===")
    return {
        "doc_id": doc_id,
        "filename": filename,
        "total_chunks": stored,
        "method": "markitdown",
    }


def run_markitdown_by_doc_id(doc_id: str) -> dict:
    """
    Fetch document from MongoDB/GCS and run the MarkItDown pipeline.

    DOCX/PPTX: downloads from gcs_original_path (original bytes) if available,
               enabling MarkItDown native extraction instead of PDF.
               Falls back to primary gcs_path if original not stored.
    All other formats: downloads from primary gcs_path.
    """
    from shared.utils.gcs_client import download_bytes

    doc = get_documents_col().find_one({"doc_id": doc_id})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    original_format = doc["original_format"]
    gcs_original_path = doc.get("gcs_original_path")

    # For DOCX/PPTX: use the original bytes for native MarkItDown extraction.
    # If gcs_original_path is missing (old doc without the field), fall back to PDF bytes.
    if gcs_original_path and original_format in ("docx", "pptx"):
        try:
            file_bytes = download_bytes(gcs_original_path)
            logger.info(
                f"Using original {original_format} bytes from {gcs_original_path} "
                f"for native MarkItDown extraction"
            )
        except Exception as e:
            logger.warning(
                f"Original bytes unavailable ({e}) — falling back to PDF from {doc['gcs_path']}"
            )
            file_bytes = download_bytes(doc["gcs_path"])
    else:
        file_bytes = download_bytes(doc["gcs_path"])
        if original_format in ("docx", "pptx") and not gcs_original_path:
            logger.info(
                f"No gcs_original_path for {original_format} — "
                f"MarkItDown will work on whatever bytes are in GCS (may be PDF)"
            )

    return run_markitdown_pipeline(
        file_bytes=file_bytes,
        filename=doc["filename"],
        doc_id=doc_id,
        original_format=original_format,
        format_provenance=doc.get("format_provenance", {}),
    )
