"""
services/rag-fl/chunker.py
Phase 3B — Content extraction and chunk creation per page type.
Returns ChunkRecord objects with embedding=None (filled by embedder.py).
GCS upload for multimodal pages happens here.
"""
import io
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber

from shared.schemas.chunk import ChunkRecord
from shared.utils.gcs_client import upload_bytes

logger = logging.getLogger("ragfl.chunker")

_TARGET_MIN = 500   # tokens
_TARGET_MAX = 800   # tokens
_HEADING_RE = re.compile(
    r"^(\d+\.\d+(\.\d+)?|[A-Z][A-Z\s]{4,}[A-Z])\s",
)


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_text_page(
    fitz_doc: fitz.Document,
    page_number: int,
    doc_id: str,
    original_format: str,
    chunk_index_start: int = 0,
) -> list[ChunkRecord]:
    """Extract text from page and split into heading-bounded 500-800 token chunks."""
    fitz_page = fitz_doc[page_number - 1]
    full_text = fitz_page.get_text()
    if not full_text.strip():
        return []

    section_title = _first_heading(full_text)
    segments = _split_by_headings(full_text)

    chunks: list[ChunkRecord] = []
    current = ""
    chunk_idx = chunk_index_start

    for seg in segments:
        combined = (current + "\n" + seg).strip()
        if len(combined) // 4 > _TARGET_MAX and current:
            chunks.append(_text_chunk(doc_id, page_number, current.strip(),
                                      original_format, section_title, chunk_idx))
            chunk_idx += 1
            current = seg
        else:
            current = combined

    if current.strip():
        if chunks and len(current) // 4 < _TARGET_MIN:
            # Merge short tail into last chunk
            last = chunks[-1]
            chunks[-1] = last.model_copy(update={"chunk_text": last.chunk_text + "\n" + current.strip()})
        else:
            chunks.append(_text_chunk(doc_id, page_number, current.strip(),
                                      original_format, section_title, chunk_idx))

    return chunks


def chunk_table_page(
    plumber_pages,
    page_number: int,
    doc_id: str,
    original_format: str,
) -> list[ChunkRecord]:
    """Extract tables via pdfplumber, return one chunk per table as Markdown."""
    chunks = []
    try:
        pl_page = plumber_pages[page_number - 1]
        tables = pl_page.extract_tables()
        for t_idx, table in enumerate(tables or []):
            md = _table_to_markdown(table)
            if not md.strip():
                continue
            chunks.append(ChunkRecord(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                page_number=page_number,
                section_title="",
                chunk_index=t_idx,
                format_provenance={"original_format": original_format, "table_index": t_idx},
                chunk_type="table",
                chunk_text=md,
                gcs_image_path=None,
                embedding=None,
                embedding_model="models/gemini-embedding-001",
                embedding_task_type="RETRIEVAL_DOCUMENT",
            ))
    except Exception as e:
        logger.warning(f"Table extraction failed page {page_number}: {e}")
    return chunks


def chunk_excel_sheet(
    doc_id: str,
    page_number: int,
    sheet_name: str,
    markdown: str,
    row_start: int,
    row_end: int,
) -> Optional[ChunkRecord]:
    """One Excel sheet → one table chunk."""
    if not markdown.strip():
        return None
    return ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        page_number=page_number,
        section_title=sheet_name,
        chunk_index=0,
        format_provenance={
            "original_format": "xlsx",
            "sheet_name": sheet_name,
            "row_start": row_start,
            "row_end": row_end,
        },
        chunk_type="table",
        chunk_text=markdown,
        gcs_image_path=None,
        embedding=None,
        embedding_model="models/gemini-embedding-001",
        embedding_task_type="RETRIEVAL_DOCUMENT",
    )


def chunk_yaml_content(doc_id: str, yaml_text: str) -> ChunkRecord:
    """YAML file → one structured_text chunk."""
    return ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        page_number=1,
        section_title="",
        chunk_index=0,
        format_provenance={"original_format": "yaml", "key_path": "root"},
        chunk_type="text",
        chunk_text=yaml_text,
        gcs_image_path=None,
        embedding=None,
        embedding_model="models/gemini-embedding-001",
        embedding_task_type="RETRIEVAL_DOCUMENT",
    )


def render_and_upload_multimodal(
    fitz_doc: fitz.Document,
    page_number: int,
    doc_id: str,
    original_format: str,
    chunk_index: int = 0,
) -> tuple[Optional[ChunkRecord], Optional[bytes]]:
    """
    Render page to PNG at 2x zoom, save locally, upload to GCS.
    Returns (ChunkRecord with empty chunk_text, png_bytes).
    chunk_text must be filled by vision.py before embedding.
    """
    output_dir = os.getenv("OUTPUT_DIR", "/output")
    gcs_bucket = os.getenv("GCS_BUCKET", "rag-fl-documents")

    try:
        png_bytes = _render_page_png(fitz_doc, page_number, doc_id, output_dir)
    except Exception as e:
        logger.error(f"PNG render failed page {page_number}: {e}")
        return None, None

    gcs_path = f"{doc_id}.{page_number}"
    gcs_image_path = None
    try:
        upload_bytes(png_bytes, gcs_path, content_type="image/png")
        gcs_image_path = f"gs://{gcs_bucket}/{gcs_path}"
    except Exception as e:
        logger.error(f"GCS upload failed page {page_number}: {e}")

    chunk = ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        page_number=page_number,
        section_title="",
        chunk_index=chunk_index,
        format_provenance={"original_format": original_format},
        chunk_type="multimodal",
        chunk_text="",          # filled by vision.py
        gcs_image_path=gcs_image_path,
        embedding=None,
        embedding_model="models/gemini-embedding-001",
        embedding_task_type="RETRIEVAL_DOCUMENT",
    )
    return chunk, png_bytes


def render_and_upload_image_file(
    image_bytes: bytes,
    doc_id: str,
    original_format: str,
    original_filename: str,
) -> tuple[Optional[ChunkRecord], bytes]:
    """For standalone JPEG/PNG files. Upload to GCS, return chunk with empty chunk_text."""
    gcs_bucket = os.getenv("GCS_BUCKET", "rag-fl-documents")
    gcs_path = f"{doc_id}.1"
    content_type = "image/jpeg" if original_format in ("jpeg", "jpg") else "image/png"

    gcs_image_path = None
    try:
        upload_bytes(image_bytes, gcs_path, content_type=content_type)
        gcs_image_path = f"gs://{gcs_bucket}/{gcs_path}"
    except Exception as e:
        logger.error(f"GCS upload failed for image {original_filename}: {e}")

    chunk = ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        page_number=1,
        section_title="",
        chunk_index=0,
        format_provenance={"original_format": original_format, "original_filename": original_filename},
        chunk_type="multimodal",
        chunk_text="",
        gcs_image_path=gcs_image_path,
        embedding=None,
        embedding_model="models/gemini-embedding-001",
        embedding_task_type="RETRIEVAL_DOCUMENT",
    )
    return chunk, image_bytes


# ── Internal helpers ──────────────────────────────────────────────────────────

def _render_page_png(fitz_doc: fitz.Document, page_number: int, doc_id: str, output_dir: str) -> bytes:
    """Render PDF page at 2x zoom. Save to /output/flat-images/. Return PNG bytes."""
    fitz_page = fitz_doc[page_number - 1]
    mat = fitz.Matrix(2, 2)
    pix = fitz_page.get_pixmap(matrix=mat)

    flat_dir = Path(output_dir) / "flat-images"
    flat_dir.mkdir(parents=True, exist_ok=True)
    out_path = flat_dir / f"{doc_id}_page_{page_number}.png"
    pix.save(str(out_path))

    png_bytes = pix.tobytes("png")
    del pix
    return png_bytes


def _first_heading(text: str) -> str:
    for line in text.split("\n"):
        line = line.strip()
        if line and _HEADING_RE.match(line):
            return line[:100]
    return ""


def _split_by_headings(text: str) -> list[str]:
    lines = text.split("\n")
    segments: list[str] = []
    current: list[str] = []
    for line in lines:
        if _HEADING_RE.match(line.strip()) and current:
            segments.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        segments.append("\n".join(current))
    return [s for s in segments if s.strip()] or [text]


def _table_to_markdown(table: list) -> str:
    if not table:
        return ""
    rows = []
    for i, row in enumerate(table):
        cells = [str(c or "").replace("|", "\\|").replace("\n", " ") for c in row]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("|" + "|".join(["---"] * len(row)) + "|")
    return "\n".join(rows)


def _text_chunk(doc_id, page_number, text, original_format, section_title, chunk_idx) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(uuid.uuid4()),
        doc_id=doc_id,
        page_number=page_number,
        section_title=section_title,
        chunk_index=chunk_idx,
        format_provenance={"original_format": original_format},
        chunk_type="text",
        chunk_text=text,
        gcs_image_path=None,
        embedding=None,
        embedding_model="models/gemini-embedding-001",
        embedding_task_type="RETRIEVAL_DOCUMENT",
    )
