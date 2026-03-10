#!/usr/bin/env python3
"""
services/rag-fl/pipeline.py
Phase 3: Per-Page Analysis + Embedding Pipeline

CLI usage (from rag-fl/ project root):
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf
  python services/rag-fl/pipeline.py --file tests/sample-docs/Churn_EDA_Report.pdf --classify-only
  python services/rag-fl/pipeline.py --doc-id <uuid>
  python services/rag-fl/pipeline.py --all
"""

import argparse
import gc
import hashlib
import io
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Path setup (must be before any local imports) ────────────────────────────
# Add project root (rag-fl/) for shared.* imports
_PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env first, then override Docker-internal hostnames for CLI execution on host.
# MongoDB: use directConnection=true to bypass replica-set discovery (host→localhost:27017
#          hits the container, but RS config says primary is "mongo:27017" which won't resolve).
# GCS:     fake-gcs is at localhost:4443 when running outside Docker.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

if not os.path.exists("/.dockerenv"):
    os.environ["MONGODB_URI"] = "mongodb://localhost:27017/ragfl?directConnection=true"
    os.environ["GCS_ENDPOINT"] = "http://localhost:4443"

import fitz  # noqa: E402
import openpyxl  # noqa: E402
import pdfplumber  # noqa: E402

from shared.schemas.chunk import ChunkRecord  # noqa: E402
from shared.schemas.page_profile import PageProfile  # noqa: E402
from shared.utils.gcs_client import download_bytes, upload_bytes  # noqa: E402
from shared.utils.mongo_client import (  # noqa: E402
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
    page_profiles as get_profiles_col,
)
from shared.utils.period_extractor import extract_report_period  # noqa: E402

from classifier import classify_non_pdf, classify_pdf_pages  # noqa: E402
from chunker import (  # noqa: E402
    chunk_excel_sheet,
    chunk_full_page_image,
    chunk_specific_table,
    chunk_table_page,
    chunk_text_page,
    chunk_whitespace_table,
    chunk_yaml_content,
    render_and_upload_image_file,
    render_and_upload_multimodal,
    render_and_upload_visual_region,
)
from embedder import embed_texts  # noqa: E402
from vision import describe_full_page, describe_page_image, is_circuit_open  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("ragfl.pipeline")

DRY_RUN_THRESHOLD = int(os.getenv("DRY_RUN_THRESHOLD", "10"))
FORCE_MIXED_MODE = os.getenv("FORCE_MIXED_MODE", "false").lower() == "true"


# ── Memory helper ─────────────────────────────────────────────────────────────

def _log_memory(page_num: int) -> None:
    try:
        import psutil
        rss_mb = psutil.Process().memory_info().rss / 1024 / 1024
        logger.info(f"Page {page_num}: {rss_mb:.0f} MB RSS")
    except Exception:
        pass


# ── Excel helper ──────────────────────────────────────────────────────────────

def _excel_sheets_to_markdown(file_bytes: bytes) -> list[dict]:
    """Convert each Excel sheet to a Markdown table. Returns list of sheet dicts."""
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    sheets = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            sheets.append({"sheet_name": sheet_name, "markdown": "", "row_start": 0, "row_end": 0})
            continue
        lines = []
        for i, row in enumerate(rows):
            cells = [str(c) if c is not None else "" for c in row]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:
                lines.append("|" + "|".join(["---"] * len(row)) + "|")
        sheets.append({
            "sheet_name": sheet_name,
            "markdown": "\n".join(lines),
            "row_start": 1,
            "row_end": len(rows),
        })
    wb.close()
    return sheets


# ── Caption detection helper ──────────────────────────────────────────────────

def _find_caption_near_visual(
    fitz_doc: fitz.Document,
    page_number: int,
    bbox: list,
    exclude_bboxes: list | None = None,
) -> str:
    """
    Scan text blocks within 25pt above or below a visual bbox for caption-like text.
    A caption is: <300 chars, horizontally overlapping with the visual, and located
    directly above or below it (gap ≤ 25pt). Blocks inside other table/visual bboxes
    (passed as exclude_bboxes) are ignored to avoid false captures.

    Returns the caption string (stripped) or "" if none found.
    """
    fitz_page = fitz_doc[page_number - 1]
    raw_blocks = fitz_page.get_text("blocks")
    vx0, vy0, vx1, vy1 = bbox
    ex_fitz = [fitz.Rect(r) for r in (exclude_bboxes or [])]
    captions: list[str] = []

    for block in raw_blocks:
        if block[6] != 0:
            continue
        bx0, by0, bx1, by1 = block[:4]
        block_text = block[4].strip()
        if not block_text or len(block_text) > 300:
            continue
        # Must have horizontal overlap with visual
        if min(bx1, vx1) - max(bx0, vx0) < 10:
            continue
        gap_above = vy0 - by1   # positive → block is above visual
        gap_below = by0 - vy1   # positive → block is below visual
        if not (0 <= gap_above <= 25 or 0 <= gap_below <= 25):
            continue
        # Skip if inside another excluded bbox (table or another visual)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        if any(er.contains(fitz.Point(cx, cy)) for er in ex_fitz):
            continue
        captions.append(block_text)

    return " ".join(captions)


# ── Core pipeline function ────────────────────────────────────────────────────

def run_pipeline(
    file_bytes: bytes,
    filename: str,
    doc_id: str,
    original_format: str,
    format_provenance: dict,
    classify_only: bool = False,
    auto_confirm: bool = False,
) -> dict:
    """
    Main pipeline: classify → write page_profiles → chunk → embed → store.
    Returns summary dict for inspection report and FastAPI response.
    """
    logger.info(f"=== Pipeline start: {filename} | doc_id={doc_id} | format={original_format} ===")

    # Update document status to PROCESSING
    get_documents_col().update_one(
        {"doc_id": doc_id},
        {"$set": {"status": "PROCESSING", "updated_at": datetime.utcnow()}},
    )

    # ── 3A: Classification ───────────────────────────────────────────────────
    if original_format in ("pdf", "pptx", "docx"):
        classifications = classify_pdf_pages(file_bytes)
    else:
        sheets_info = format_provenance.get("sheets")
        page_count = format_provenance.get("page_count", 1)
        if original_format in ("xlsx", "xls"):
            page_count = len(sheets_info) if sheets_info else 1
        classifications = classify_non_pdf(original_format, page_count, sheets_info)

    # Write page_profiles to MongoDB
    profiles_col = get_profiles_col()
    for cls in classifications:
        profile = PageProfile(
            doc_id=doc_id,
            page_number=cls.page_number,
            page_type=cls.page_type,
            detected_elements=cls.detected_elements,
            processing_recommendation=cls.processing_recommendation,
            estimated_text_tokens=cls.estimated_text_tokens,
            has_tables=cls.has_tables,
            text_ratio=cls.text_ratio,
            image_ratio=cls.image_ratio,
        )
        profiles_col.replace_one(
            {"doc_id": doc_id, "page_number": cls.page_number},
            profile.to_mongo(),
            upsert=True,
        )

    logger.info(f"Classification complete: {len(classifications)} pages written to page_profiles")

    if classify_only:
        get_documents_col().update_one(
            {"doc_id": doc_id},
            {"$set": {"status": "UPLOADED", "updated_at": datetime.utcnow()}},
        )
        return {"doc_id": doc_id, "filename": filename, "classify_only": True,
                "pages": len(classifications), "classifications": classifications}

    # ── Pre-flight: count Gemini calls ───────────────────────────────────────
    # Count visual elements (element-based) or fall back to page count (legacy)
    gemini_call_estimate = 0
    for c in classifications:
        if c.page_type == "skip":
            continue
        struct_elements = [e for e in c.detected_elements if isinstance(e, dict)]
        if struct_elements:
            gemini_call_estimate += sum(
                1 for e in struct_elements
                if e.get("type") in ("visual", "full_page_image")
            )
        elif c.page_type in ("multimodal", "mixed", "full_page_image"):
            gemini_call_estimate += 1

    if gemini_call_estimate > DRY_RUN_THRESHOLD and not auto_confirm:
        print(f"\n⚠️  Estimated {gemini_call_estimate} Gemini Vision calls "
              f"(threshold={DRY_RUN_THRESHOLD}). Confirm? [y/N] ", end="", flush=True)
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            logger.info("Aborted by user. No API calls made.")
            get_documents_col().update_one(
                {"doc_id": doc_id},
                {"$set": {"status": "UPLOADED", "updated_at": datetime.utcnow()}},
            )
            return {"doc_id": doc_id, "filename": filename, "aborted": True}

    # ── 3B: Chunking + Embedding ──────────────────────────────────────────────
    all_chunks: list[ChunkRecord] = []
    # Vision chunks need their chunk_text filled before batch embedding
    vision_pending: list[tuple[ChunkRecord, bytes]] = []  # (chunk, image_bytes)
    needs_vision_retry: list[str] = []  # chunk_ids skipped due to circuit breaker

    gemini_calls_made = 0
    page_chunk_summary: list[dict] = []  # for inspection report

    if original_format in ("pdf", "pptx", "docx"):
        fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
        with pdfplumber.open(io.BytesIO(file_bytes)) as plumber_doc:
            for cls in classifications:
                pnum = cls.page_number
                page_chunks: list[ChunkRecord] = []

                if cls.page_type == "skip":
                    logger.info(f"Page {pnum}: skip — no embedding created")

                else:
                    struct_elements = [
                        e for e in cls.detected_elements
                        if isinstance(e, dict) and e.get("type") not in (None, "none")
                    ]

                    if struct_elements:
                        # ── Full-page image dispatch ──────────────────────────
                        # For pages classified as full_page_image, capture the
                        # entire page as one high-res image and ask Gemini to
                        # describe all content holistically (table + chart + text).
                        if any(e.get("type") == "full_page_image" for e in struct_elements):
                            fp_chunk, fp_bytes = chunk_full_page_image(
                                fitz_doc, pnum, doc_id, original_format,
                                chunk_index=0,
                            )
                            if fp_chunk:
                                desc = describe_full_page(fp_bytes)
                                if desc:
                                    fp_chunk.chunk_text = desc
                                    gemini_calls_made += 1
                                else:
                                    fp_chunk.chunk_text = (
                                        f"[Page {pnum}: full-page description unavailable]"
                                    )
                                    if is_circuit_open():
                                        needs_vision_retry.append(fp_chunk.chunk_id)
                                page_chunks.append(fp_chunk)
                            if fp_bytes:
                                del fp_bytes

                        else:
                            # ── Element-based dispatch ────────────────────────
                            chunk_idx = 0
                            visual_idx = 0

                            # Collect bboxes to exclude from text extraction.
                            # Only RELIABLE (line-drawn) tables and visuals are excluded.
                            # Soft tables (whitespace-aligned, text+lines heuristic) are NOT
                            # excluded — their bboxes may overlap legitimate paragraph text,
                            # and the over-exclusion was causing missing subtitles/paragraphs.
                            exclude_bboxes = []
                            for e in struct_elements:
                                if not e.get("bbox"):
                                    continue
                                if e["type"] == "visual":
                                    exclude_bboxes.append(e["bbox"])
                                elif e["type"] == "table" and not e.get("is_whitespace_table") and not e.get("rows"):
                                    # Only pdfplumber LINES-strategy tables (no rows key = not
                                    # extracted by whitespace or text+lines heuristics)
                                    exclude_bboxes.append(e["bbox"])

                            # Text: one call covers all text blocks on the page
                            if any(e["type"] == "text" for e in struct_elements):
                                text_chunks = chunk_text_page(
                                    fitz_doc, pnum, doc_id, original_format,
                                    chunk_index_start=chunk_idx,
                                    exclude_rects=exclude_bboxes or None,
                                )
                                page_chunks.extend(text_chunks)
                                chunk_idx += len(text_chunks)

                            # Tables: one chunk per detected table element
                            for elem in struct_elements:
                                if elem["type"] != "table":
                                    continue
                                if elem.get("rows"):
                                    # Pre-extracted rows (whitespace or text+lines strategy)
                                    tbl_chunks = chunk_whitespace_table(
                                        elem["rows"], pnum, doc_id, original_format,
                                        table_index=elem["table_index"],
                                        chunk_index_start=chunk_idx,
                                    )
                                else:
                                    tbl_chunks = chunk_specific_table(
                                        plumber_doc.pages, pnum, doc_id, original_format,
                                        table_index=elem["table_index"],
                                        chunk_index_start=chunk_idx,
                                    )
                                page_chunks.extend(tbl_chunks)
                                chunk_idx += len(tbl_chunks)

                            # Visuals: one Gemini call per detected visual region
                            for elem in struct_elements:
                                if elem["type"] != "visual":
                                    continue
                                vis_chunk, png_bytes = render_and_upload_visual_region(
                                    fitz_doc, pnum, elem["bbox"], doc_id, original_format,
                                    chunk_index=chunk_idx, visual_index=visual_idx,
                                )
                                if vis_chunk:
                                    desc = describe_page_image(png_bytes)
                                    if desc:
                                        # Prepend figure/chart caption if found near the bbox
                                        caption = _find_caption_near_visual(
                                            fitz_doc, pnum, elem["bbox"], exclude_bboxes
                                        )
                                        vis_chunk.chunk_text = (
                                            f"{caption}\n\n{desc}" if caption else desc
                                        )
                                        gemini_calls_made += 1
                                    else:
                                        vis_chunk.chunk_text = (
                                            f"[Page {pnum}: image description unavailable]"
                                        )
                                        if is_circuit_open():
                                            needs_vision_retry.append(vis_chunk.chunk_id)
                                    page_chunks.append(vis_chunk)
                                    chunk_idx += 1
                                    visual_idx += 1
                                if png_bytes:
                                    del png_bytes

                    else:
                        # ── Legacy fallback (FORCE_MIXED_MODE / non-struct elements) ──
                        if cls.page_type == "text":
                            page_chunks = chunk_text_page(fitz_doc, pnum, doc_id, original_format)

                        elif cls.page_type == "table":
                            page_chunks = chunk_table_page(
                                plumber_doc.pages, pnum, doc_id, original_format
                            )

                        elif cls.page_type in ("multimodal", "mixed"):
                            text_parts = []
                            if cls.page_type == "mixed":
                                text_parts = chunk_text_page(
                                    fitz_doc, pnum, doc_id, original_format,
                                    chunk_index_start=0,
                                )
                            vis_chunk, png_bytes = render_and_upload_multimodal(
                                fitz_doc, pnum, doc_id, original_format,
                                chunk_index=len(text_parts),
                            )
                            if vis_chunk:
                                desc = describe_page_image(png_bytes)
                                if desc:
                                    vis_chunk.chunk_text = desc
                                    gemini_calls_made += 1
                                else:
                                    vis_chunk.chunk_text = (
                                        f"[Page {pnum}: image description unavailable]"
                                    )
                                    if is_circuit_open():
                                        needs_vision_retry.append(vis_chunk.chunk_id)
                                page_chunks = text_parts + [vis_chunk]
                            else:
                                page_chunks = text_parts
                            del png_bytes

                all_chunks.extend(page_chunks)
                page_chunk_summary.append({
                    "page_number": pnum,
                    "page_type": cls.page_type,
                    "chunk_count": len(page_chunks),
                    "preview": _chunk_preview(page_chunks),
                })

                # Memory management
                if pnum % 10 == 0:
                    gc.collect()
                    _log_memory(pnum)

        fitz_doc.close()

    elif original_format in ("xlsx", "xls"):
        sheets_md = _excel_sheets_to_markdown(file_bytes)
        for cls in classifications:
            pnum = cls.page_number
            sheet_data = sheets_md[pnum - 1] if pnum - 1 < len(sheets_md) else {}
            chunk = chunk_excel_sheet(
                doc_id=doc_id,
                page_number=pnum,
                sheet_name=sheet_data.get("sheet_name", f"Sheet{pnum}"),
                markdown=sheet_data.get("markdown", ""),
                row_start=sheet_data.get("row_start", 0),
                row_end=sheet_data.get("row_end", 0),
            )
            if chunk:
                all_chunks.append(chunk)
                page_chunk_summary.append({
                    "page_number": pnum,
                    "page_type": "table",
                    "chunk_count": 1,
                    "preview": chunk.chunk_text[:80],
                })

    elif original_format in ("yaml", "yml"):
        yaml_text = file_bytes.decode("utf-8", errors="replace")
        chunk = chunk_yaml_content(doc_id, yaml_text)
        all_chunks.append(chunk)
        page_chunk_summary.append({
            "page_number": 1, "page_type": "structured_text",
            "chunk_count": 1, "preview": yaml_text[:80],
        })

    elif original_format in ("jpeg", "jpg", "png"):
        chunk, img_bytes = render_and_upload_image_file(
            file_bytes, doc_id, original_format, filename
        )
        if chunk:
            desc = describe_page_image(img_bytes)
            if desc:
                chunk.chunk_text = desc
                gemini_calls_made += 1
            else:
                chunk.chunk_text = "[image description unavailable]"
            all_chunks.append(chunk)
            page_chunk_summary.append({
                "page_number": 1, "page_type": "multimodal",
                "chunk_count": 1, "preview": f"Gemini: {chunk.chunk_text[:80]}",
            })

    logger.info(f"Chunking complete: {len(all_chunks)} chunks, {gemini_calls_made} Gemini Vision calls")

    # ── Batch embedding ───────────────────────────────────────────────────────
    if all_chunks:
        texts = [c.chunk_text for c in all_chunks]
        _embedding_model = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
        logger.info(f"Embedding {len(texts)} chunks via {_embedding_model} ...")
        embeddings = embed_texts(texts)
        for chunk, emb in zip(all_chunks, embeddings):
            chunk.embedding = emb
            chunk.embedding_model = _embedding_model
            chunk.embedding_task_type = "RETRIEVAL_DOCUMENT"

    # ── Store to MongoDB doc_embeddings ───────────────────────────────────────
    embeddings_col = get_embeddings_col()
    stored = 0
    for chunk in all_chunks:
        doc = chunk.to_mongo()
        # Track circuit-breaker flag
        if chunk.chunk_id in needs_vision_retry:
            doc["needs_vision_retry"] = True
        embeddings_col.replace_one(
            {"chunk_id": chunk.chunk_id},
            doc,
            upsert=True,
        )
        stored += 1

    # ── Update document status ────────────────────────────────────────────────
    get_documents_col().update_one(
        {"doc_id": doc_id},
        {"$set": {"status": "EMBEDDED", "updated_at": datetime.utcnow()}},
    )

    summary = {
        "doc_id": doc_id,
        "filename": filename,
        "total_pages": len(classifications),
        "total_chunks": stored,
        "gemini_calls": gemini_calls_made,
        "needs_vision_retry": len(needs_vision_retry),
        "page_summary": page_chunk_summary,
    }

    _print_inspection_report(summary, classifications)
    return summary


def _chunk_preview(chunks: list[ChunkRecord]) -> str:
    if not chunks:
        return "—"
    first = chunks[0]
    if first.chunk_type == "multimodal" and first.chunk_text:
        return f"Gemini: '{first.chunk_text[:70]}'"
    if first.chunk_type == "table":
        return first.chunk_text.split("\n")[0][:70]
    return f"'{first.chunk_text[:70]}'"


def _safe_print(text: str) -> None:
    """Print text, replacing any characters unsupported by the terminal encoding."""
    enc = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
    print(text.encode(enc, errors="replace").decode(enc))


def _print_inspection_report(summary: dict, classifications) -> None:
    _safe_print("\n" + "=" * 60)
    _safe_print("=== EMBEDDING INSPECTION REPORT ===")
    _safe_print(
        f"Document: {summary['filename']} | {summary['total_pages']} pages | "
        f"{summary['total_chunks']} chunks | {summary['gemini_calls']} Gemini calls"
    )
    _safe_print("=" * 60)
    cls_map = {c.page_number: c for c in classifications}
    for ps in summary["page_summary"]:
        pnum = ps["page_number"]
        cls = cls_map.get(pnum)
        ptype = cls.page_type if cls else ps["page_type"]
        _safe_print(
            f"Page {pnum:3d} | {ptype:<13s} | {ps['chunk_count']} chunk(s) | {ps['preview']}"
        )
    # Print skipped pages
    for s in classifications:
        if s.page_type == "skip":
            _safe_print(f"Page {s.page_number:3d} | skip          | 0 chunks | -")
    _safe_print("=" * 60 + "\n")


# ── Ingestion helpers (CLI mode — bypass HTTP) ────────────────────────────────

def ingest_file_direct(file_path: Path) -> tuple[str, bytes, str, str, dict]:
    """
    Ingest a file directly (no HTTP). Returns (doc_id, file_bytes, filename, original_format, format_provenance).
    Handles deduplication: if hash exists, returns existing doc_id.
    """
    file_bytes = file_path.read_bytes()
    filename = file_path.name
    content_hash = hashlib.sha256(file_bytes).hexdigest()

    # Dedup check
    existing = get_documents_col().find_one({"content_hash": content_hash}, {"doc_id": 1})
    if existing:
        existing_id = existing["doc_id"]
        logger.info(f"Duplicate: {filename} → existing doc_id={existing_id}")
        doc = get_documents_col().find_one({"doc_id": existing_id})
        return (existing_id, file_bytes, filename,
                doc.get("original_format", ""), doc.get("format_provenance", {}))

    # Detect format via extension (mirrors registry logic)
    ext = file_path.suffix.lower().lstrip(".")
    format_map = {
        "pdf": "pdf", "xlsx": "xlsx", "xls": "xls",
        "yaml": "yaml", "yml": "yaml",
        "jpeg": "jpeg", "jpg": "jpeg", "png": "png",
        "pptx": "pptx", "docx": "docx",
    }
    original_format = format_map.get(ext, ext)

    # Page count
    page_count = 1
    format_provenance: dict = {"original_format": original_format}
    if original_format == "pdf":
        fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = fitz_doc.page_count
        meta = fitz_doc.metadata or {}
        fitz_doc.close()
        format_provenance = {"original_format": "pdf", "page_count": page_count}
    elif original_format in ("xlsx", "xls"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        sheets = [{"name": n, "row_count": wb[n].max_row or 0} for n in wb.sheetnames]
        wb.close()
        page_count = len(sheets)
        format_provenance = {"original_format": "xlsx", "sheets": sheets}

    # Chrono metadata
    mime_map = {"pdf": "application/pdf", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    mime_type = mime_map.get(original_format, f"application/{original_format}")
    chrono = extract_report_period(filename, file_bytes, mime_type)

    # Upload to GCS
    doc_id = str(uuid.uuid4())
    gcs_path = f"{doc_id}/{filename}"
    gcs_bucket = os.getenv("GCS_BUCKET", "rag-fl-documents")
    upload_bytes(file_bytes, gcs_path, content_type=mime_type)
    logger.info(f"Uploaded to GCS: gs://{gcs_bucket}/{gcs_path}")

    # Save to MongoDB
    now = datetime.utcnow()
    get_documents_col().insert_one({
        "_id": doc_id, "doc_id": doc_id, "filename": filename,
        "original_format": original_format, "gcs_path": gcs_path,
        "total_pages": page_count, "status": "UPLOADED",
        "source_channel": "cli", "format_provenance": format_provenance,
        "content_hash": content_hash, "is_duplicate_of": None,
        **{k: chrono.get(k) for k in (
            "report_series", "report_period", "report_period_start",
            "report_period_end", "report_frequency", "period_confidence", "extraction_method"
        )},
        "upload_timestamp": now, "uploaded_by": "cli",
        "created_at": now, "updated_at": now,
    })
    logger.info(f"Ingested: {filename} → doc_id={doc_id}, pages={page_count}, "
                f"report_period={chrono.get('report_period')}")
    return doc_id, file_bytes, filename, original_format, format_provenance


def process_by_doc_id(doc_id: str, classify_only: bool = False, auto_confirm: bool = False) -> dict:
    """Fetch a document from MongoDB/GCS and run the pipeline."""
    doc = get_documents_col().find_one({"doc_id": doc_id})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    gcs_path = doc["gcs_path"]
    logger.info(f"Downloading from GCS: {gcs_path}")
    file_bytes = download_bytes(gcs_path)

    return run_pipeline(
        file_bytes=file_bytes,
        filename=doc["filename"],
        doc_id=doc_id,
        original_format=doc["original_format"],
        format_provenance=doc.get("format_provenance", {}),
        classify_only=classify_only,
        auto_confirm=auto_confirm,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="rag-fl Phase 3 pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", metavar="PATH", help="Process a specific file")
    group.add_argument("--doc-id", metavar="UUID", help="Process an already-ingested document")
    group.add_argument("--all", action="store_true", help="Process all UPLOADED documents")

    parser.add_argument("--classify-only", action="store_true",
                        help="Run classification only (no embedding, no API calls)")
    parser.add_argument("--yes", action="store_true",
                        help="Auto-confirm Gemini call count warning")
    args = parser.parse_args()

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            sys.exit(1)
        doc_id, file_bytes, filename, original_format, format_provenance = ingest_file_direct(file_path)
        run_pipeline(
            file_bytes=file_bytes,
            filename=filename,
            doc_id=doc_id,
            original_format=original_format,
            format_provenance=format_provenance,
            classify_only=args.classify_only,
            auto_confirm=args.yes,
        )

    elif args.doc_id:
        process_by_doc_id(args.doc_id, classify_only=args.classify_only, auto_confirm=args.yes)

    elif args.all:
        docs = list(get_documents_col().find(
            {"status": {"$in": ["UPLOADED", "FAILED"]}},
            {"doc_id": 1, "filename": 1},
        ))
        logger.info(f"Processing {len(docs)} documents with status=UPLOADED/FAILED")
        for d in docs:
            try:
                process_by_doc_id(d["doc_id"], classify_only=args.classify_only, auto_confirm=args.yes)
            except Exception as e:
                logger.error(f"Failed to process {d['filename']} ({d['doc_id']}): {e}")
                get_documents_col().update_one(
                    {"doc_id": d["doc_id"]},
                    {"$set": {"status": "FAILED", "updated_at": datetime.utcnow()}},
                )


if __name__ == "__main__":
    main()
