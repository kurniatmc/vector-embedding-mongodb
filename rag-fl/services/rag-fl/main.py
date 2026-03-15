"""
services/rag-fl/main.py
FastAPI service for Phases 3-6.
Port: 8004 (RAG_FL_PORT)

Core endpoints (this file):
  POST /process                                → trigger pipeline for a doc_id
  GET  /health                                 → health check
  GET  /documents                              → list all documents with status
  GET  /document/{doc_id}/status               → processing status
  GET  /document/{doc_id}/pages                → per-page profiles
  GET  /document/{doc_id}/chunks/{page_number} → chunks for one page
  GET  /document/{doc_id}/explorer             → page explorer (GCS-based, stateless)
  GET  /document/{doc_id}/page/{page}/details  → single page details with images
  GET  /image/{doc_id}/{page_number}           → GCS image proxy (Phase 4)
  GET  /config                                 → runtime config

Citation endpoints (citation.py router — Phase 5):
  POST /citations/generate
  GET  /citations/preview/{doc_id}/{page}
  GET  /provenance/document/{doc_id}
  GET  /provenance/chunk/{chunk_id}

Search endpoints (search.py router — Phase 6):
  POST /search                                 → global search with filters
  POST /search/within/{doc_id}                 → document-scoped search
  GET  /document/{doc_id}/summary              → doc stats + page-type breakdown
"""
import asyncio
import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from shared.utils.mongo_client import (
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
    page_profiles as get_profiles_col,
)

# pipeline imported here for /process endpoint
# (only imported when endpoint is called to avoid startup cost)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ragfl.main")

from citation import router as citation_router
from comparison import router as comparison_router
from search import router as search_router

app = FastAPI(
    title="rag-fl Pipeline Service",
    version="6.0.0",
    description="Per-page analysis, embedding pipeline, document exploration, and search API.",
)

# Phase 5 — Citation Engine endpoints
app.include_router(citation_router)

# Phase 6 — Search & Retrieval API endpoints
app.include_router(search_router)

# Comparison — PyMuPDF vs MarkItDown endpoints
app.include_router(comparison_router)

# Allow Next.js UI (localhost:3001) to call this API from the browser
# CORS_ORIGINS can be comma-separated list for production (e.g., "https://app.domain.com,https://admin.domain.com")
_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ───────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    doc_id: str
    classify_only: bool = False
    # "pymupdf" | "markitdown" | "both" (default — runs both for comparison)
    processing_method: str = "both"


class ProcessResponse(BaseModel):
    doc_id: str
    filename: str
    status: str
    message: str


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "up", "service": "rag-fl"}


# ── Pipeline trigger ──────────────────────────────────────────────────────────

@app.post("/process", response_model=ProcessResponse)
async def process_document(req: ProcessRequest, background_tasks: BackgroundTasks):
    """Trigger Phase 3 pipeline for an already-ingested document."""
    doc = get_documents_col().find_one({"doc_id": req.doc_id}, {"filename": 1, "status": 1})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {req.doc_id}")

    if doc.get("status") == "PROCESSING":
        return ProcessResponse(
            doc_id=req.doc_id,
            filename=doc.get("filename", ""),
            status="PROCESSING",
            message="Pipeline already running for this document.",
        )

    # Run synchronously (POC — acceptable for demo)
    from pipeline import process_by_doc_id

    method = req.processing_method or "both"
    pymupdf_result: dict = {}
    markitdown_result: dict = {}

    # ── PyMuPDF pipeline (existing, always runs unless markitdown-only) ───────
    if method in ("pymupdf", "both"):
        try:
            pymupdf_result = process_by_doc_id(
                req.doc_id, classify_only=req.classify_only, auto_confirm=True
            )
        except Exception as e:
            logger.error(f"PyMuPDF pipeline failed for {req.doc_id}: {e}")
            raise HTTPException(status_code=500, detail=f"PyMuPDF pipeline failed: {e}")

    # ── MarkItDown pipeline (parallel comparison, non-fatal if it fails) ──────
    if method in ("markitdown", "both") and not req.classify_only:
        try:
            from markitdown_pipeline import run_markitdown_by_doc_id, should_process_with_markitdown
            _doc_meta = get_documents_col().find_one(
                {"doc_id": req.doc_id}, {"filename": 1, "original_format": 1}
            ) or {}
            if should_process_with_markitdown(
                _doc_meta.get("filename", ""),
                _doc_meta.get("original_format", ""),
            ):
                markitdown_result = run_markitdown_by_doc_id(req.doc_id)
                logger.info(
                    f"MarkItDown pipeline complete for {req.doc_id}: "
                    f"{markitdown_result.get('total_chunks', 0)} chunks"
                )
                # Update document status to EMBEDDED (only if markitdown-only, not "both")
                if method == "markitdown":
                    get_documents_col().update_one(
                        {"doc_id": req.doc_id},
                        {"$set": {"status": "EMBEDDED", "updated_at": datetime.utcnow()}}
                    )
            else:
                logger.info(f"MarkItDown skipped for {req.doc_id} (guard: format/baseline)")
        except Exception as e:
            logger.warning(f"MarkItDown pipeline failed for {req.doc_id} (non-fatal): {e}")
            markitdown_result = {"total_chunks": 0, "error": str(e)}

    # For Excel: delete PyMuPDF TEXT/TABLE chunks (avoid duplication), keep VISUAL chunks (charts)
    if method == "both" and not req.classify_only:
        _doc_meta = get_documents_col().find_one(
            {"doc_id": req.doc_id}, {"original_format": 1}
        ) or {}
        if _doc_meta.get("original_format") in ("xlsx", "xls", "csv"):
            deleted = get_embeddings_col().delete_many({
                "doc_id": req.doc_id,
                "processing_method": {"$ne": "markitdown"},
                "chunk_type": {"$in": ["text", "table"]}  # Delete text/table, keep multimodal/visual
            })
            if deleted.deleted_count > 0:
                logger.info(
                    f"Deleted {deleted.deleted_count} PyMuPDF text/table chunks for Excel "
                    f"(MarkItDown primary for tables, Vision kept for charts)"
                )

    total_pymupdf = pymupdf_result.get("total_chunks", 0)
    total_mkd = markitdown_result.get("total_chunks", 0)
    msg = (
        f"PyMuPDF: {total_pymupdf} chunks"
        + (f" | MarkItDown: {total_mkd} chunks" if method in ("markitdown", "both") else "")
        + (f" | {pymupdf_result.get('gemini_calls', 0)} Gemini calls" if pymupdf_result else "")
    )

    return ProcessResponse(
        doc_id=req.doc_id,
        filename=doc.get("filename", ""),
        status="EMBEDDED" if not req.classify_only else "UPLOADED",
        message=msg,
    )


# ── Document listing ──────────────────────────────────────────────────────────

@app.get("/documents")
async def list_documents(limit: int = Query(50), skip: int = Query(0)):
    """List all documents with chunk counts."""
    docs = list(
        get_documents_col()
        .find({}, {"_id": 0, "doc_id": 1, "filename": 1, "original_format": 1,
                   "total_pages": 1, "status": 1, "report_period": 1,
                   "period_confidence": 1, "created_at": 1})
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    for d in docs:
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        d["chunk_count"] = get_embeddings_col().count_documents({"doc_id": d["doc_id"]})
    return {"documents": docs, "count": len(docs)}


# ── Per-document status ───────────────────────────────────────────────────────

@app.get("/document/{doc_id}/status")
async def document_status(doc_id: str):
    doc = get_documents_col().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    for ts in ("created_at", "updated_at", "upload_timestamp"):
        if doc.get(ts):
            doc[ts] = doc[ts].isoformat()
    doc["chunk_count"] = get_embeddings_col().count_documents({"doc_id": doc_id})
    doc["page_profile_count"] = get_profiles_col().count_documents({"doc_id": doc_id})
    return doc


# ── Per-page profiles ─────────────────────────────────────────────────────────

@app.get("/document/{doc_id}/pages")
async def document_pages(doc_id: str):
    """Return per-page profiles for the document."""
    profiles = list(
        get_profiles_col()
        .find({"doc_id": doc_id}, {"_id": 0})
        .sort("page_number", 1)
    )
    if not profiles:
        raise HTTPException(status_code=404, detail="No page profiles found. Run pipeline first.")
    for p in profiles:
        p["chunk_count"] = get_embeddings_col().count_documents(
            {"doc_id": doc_id, "page_number": p["page_number"]}
        )
        if p.get("created_at"):
            p["created_at"] = p["created_at"].isoformat()
    return {"doc_id": doc_id, "pages": profiles, "count": len(profiles)}


# ── Per-page chunks ───────────────────────────────────────────────────────────

@app.get("/document/{doc_id}/chunks/{page_number}")
async def document_page_chunks(doc_id: str, page_number: int):
    """Return all chunks for a specific page."""
    chunks = list(
        get_embeddings_col()
        .find(
            {"doc_id": doc_id, "page_number": page_number},
            {
                "_id": 0, "chunk_id": 1, "chunk_type": 1, "chunk_text": 1,
                "chunk_index": 1, "section_title": 1, "gcs_image_path": 1,
                "format_provenance": 1, "bounding_box": 1,
                "embedding_model": 1, "embedding_task_type": 1,
            }
        )
        .sort("chunk_index", 1)
    )
    if not chunks:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for page {page_number}. Run pipeline first.",
        )
    # Include embedding dimension as confirmation (do not return the full vector)
    full_chunks = list(get_embeddings_col().find(
        {"doc_id": doc_id, "page_number": page_number}, {"embedding": 1, "chunk_id": 1}
    ))
    emb_dim_map = {c["chunk_id"]: len(c.get("embedding") or []) for c in full_chunks}
    for chunk in chunks:
        chunk["embedding_dims"] = emb_dim_map.get(chunk["chunk_id"], 0)

    return {"doc_id": doc_id, "page_number": page_number, "chunks": chunks, "count": len(chunks)}


# ── GCS image proxy (Phase 4 — avoids CORS from browser to fake-gcs) ─────────

@app.get("/image/{doc_id}/{page_number}")
async def get_page_image(doc_id: str, page_number: int, v: int = Query(0)):
    """
    Proxy a page PNG from GCS to the browser. Avoids CORS issues.
    
    New GCS path format: {doc_id}/page_{page_number}/{chunk_id}
    v=0 (default) → first visual on the page
    v>0           → additional visual crops on the same page
    
    Looks up the chunk in MongoDB to get the correct gcs_image_path.
    """
    from shared.utils.gcs_client import download_bytes

    # Find image chunks for this doc_id + page_number
    # Include both "multimodal" and "full_page_image" chunk types
    # Sort by chunk_index to maintain visual order (v=0, v=1, v=2, ...)
    chunks = list(
        get_embeddings_col()
        .find(
            {
                "doc_id": doc_id,
                "page_number": page_number,
                "chunk_type": {"$in": ["multimodal", "full_page_image"]},
                "gcs_image_path": {"$exists": True, "$ne": None},
            },
            {"gcs_image_path": 1, "chunk_index": 1},
        )
        .sort("chunk_index", 1)
        .skip(v)
        .limit(1)
    )

    if not chunks:
        raise HTTPException(
            status_code=404, 
            detail=f"Image not found: doc_id={doc_id}, page={page_number}, visual_index={v}"
        )

    gcs_image_path = chunks[0].get("gcs_image_path")
    if not gcs_image_path:
        raise HTTPException(status_code=404, detail=f"No GCS path for image: doc_id={doc_id}, page={page_number}, v={v}")

    # Extract gcs_path from gs://bucket/path format
    try:
        gcs_path = gcs_image_path.replace("gs://", "").split("/", 1)[1]
    except (IndexError, AttributeError):
        raise HTTPException(status_code=500, detail=f"Invalid GCS path format: {gcs_image_path}")

    try:
        image_bytes = download_bytes(gcs_path)
        return Response(content=image_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch image: {e}")


# ── Page Explorer (GCS-based, stateless) ─────────────────────────────────────

@app.get("/document/{doc_id}/explorer")
async def document_page_explorer(doc_id: str):
    """
    Page Explorer - Returns complete page-level view from MongoDB/GCS.
    
    This endpoint is stateless - all data comes from MongoDB and GCS.
    No local Docker storage is used, so data persists across restarts.
    
    Returns for each page:
    - page_number, page_type, detected_elements
    - visual_count: number of images available
    - images: list of {chunk_id, gcs_image_path, chunk_index} for UI navigation
    """
    # 1. Verify document exists
    doc = get_documents_col().find_one(
        {"doc_id": doc_id},
        {"_id": 0, "filename": 1, "total_pages": 1, "status": 1, "original_format": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    
    # 2. Get all page profiles
    profiles = list(
        get_profiles_col()
        .find({"doc_id": doc_id}, {"_id": 0})
        .sort("page_number", 1)
    )
    
    # 3. Get all image chunks (multimodal + full_page_image) grouped by page
    image_chunks = list(
        get_embeddings_col()
        .find(
            {
                "doc_id": doc_id,
                "chunk_type": {"$in": ["multimodal", "full_page_image"]},
                "gcs_image_path": {"$exists": True, "$ne": None},
            },
            {
                "_id": 0, "chunk_id": 1, "page_number": 1, 
                "gcs_image_path": 1, "chunk_index": 1,
                "format_provenance": 1, "section_title": 1,
            }
        )
        .sort("chunk_index", 1)
    )
    
    # Group images by page_number
    images_by_page = {}
    for img in image_chunks:
        pnum = img.get("page_number", 1)
        if pnum not in images_by_page:
            images_by_page[pnum] = []
        images_by_page[pnum].append({
            "chunk_id": img.get("chunk_id"),
            "gcs_image_path": img.get("gcs_image_path"),
            "chunk_index": img.get("chunk_index"),
            "is_full_page": img.get("format_provenance", {}).get("full_page", False),
            "visual_index": img.get("format_provenance", {}).get("visual_index", 0),
        })
    
    # 4. Build page explorer data
    pages = []
    for profile in profiles:
        pnum = profile["page_number"]
        page_images = images_by_page.get(pnum, [])
        
        pages.append({
            "page_number": pnum,
            "page_type": profile.get("page_type", "unknown"),
            "processing_recommendation": profile.get("processing_recommendation", ""),
            "has_tables": profile.get("has_tables", False),
            "text_ratio": profile.get("text_ratio", 0),
            "image_ratio": profile.get("image_ratio", 0),
            "estimated_text_tokens": profile.get("estimated_text_tokens", 0),
            "visual_count": len(page_images),
            "images": page_images,
            "detected_elements": profile.get("detected_elements", []),
        })
    
    # 5. Summary stats
    total_images = sum(len(imgs) for imgs in images_by_page.values())
    pages_with_images = len(images_by_page)
    
    return {
        "doc_id": doc_id,
        "filename": doc.get("filename", ""),
        "status": doc.get("status", ""),
        "original_format": doc.get("original_format", ""),
        "total_pages": doc.get("total_pages", len(profiles)),
        "pages": pages,
        "summary": {
            "total_pages": len(profiles),
            "pages_with_images": pages_with_images,
            "total_images": total_images,
        }
    }


@app.get("/document/{doc_id}/page/{page_number}/details")
async def page_details(doc_id: str, page_number: int):
    """
    Get detailed view of a single page including all chunks and images.
    Completely stateless - fetches from MongoDB/GCS on each request.
    """
    # Verify document
    doc = get_documents_col().find_one(
        {"doc_id": doc_id},
        {"_id": 0, "filename": 1, "original_format": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    
    # Get page profile
    profile = get_profiles_col().find_one(
        {"doc_id": doc_id, "page_number": page_number},
        {"_id": 0}
    )
    
    # Get all chunks for this page (all types)
    all_chunks = list(
        get_embeddings_col()
        .find(
            {"doc_id": doc_id, "page_number": page_number},
            {
                "_id": 0, "chunk_id": 1, "chunk_type": 1, "chunk_text": 1,
                "chunk_index": 1, "section_title": 1, "gcs_image_path": 1,
                "format_provenance": 1, "embedding_model": 1,
            }
        )
        .sort("chunk_index", 1)
    )
    
    # Separate chunks by type
    text_chunks = [c for c in all_chunks if c.get("chunk_type") == "text"]
    table_chunks = [c for c in all_chunks if c.get("chunk_type") == "table"]
    image_chunks = [c for c in all_chunks if c.get("chunk_type") in ["multimodal", "full_page_image"]]
    
    # Build image URLs for the UI (using our /image proxy endpoint)
    images = []
    for i, chunk in enumerate(image_chunks):
        if chunk.get("gcs_image_path"):
            images.append({
                "chunk_id": chunk.get("chunk_id"),
                "chunk_index": chunk.get("chunk_index"),
                "proxy_url": f"/image/{doc_id}/{page_number}?v={i}",
                "gcs_image_path": chunk.get("gcs_image_path"),
                "is_full_page": chunk.get("format_provenance", {}).get("full_page", False),
                "visual_index": chunk.get("format_provenance", {}).get("visual_index", 0),
            })
    
    return {
        "doc_id": doc_id,
        "filename": doc.get("filename", ""),
        "page_number": page_number,
        "page_profile": profile,
        "chunks": {
            "text": text_chunks,
            "tables": table_chunks,
            "multimodal": multimodal_chunks,
        },
        "images": images,
        "total_chunks": len(all_chunks),
    }


# ── Config endpoint (Phase 4 top bar — FORCE_MIXED_MODE indicator) ────────────

@app.get("/config")
async def get_config():
    """Return relevant runtime configuration for the UI."""
    return {
        "force_mixed_mode": os.getenv("FORCE_MIXED_MODE", "false"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "dry_run_threshold": int(os.getenv("DRY_RUN_THRESHOLD", "10")),
    }


# ── Startup seeding (Problem 3) ───────────────────────────────────────────────

_DEFAULT_SEED_FILES = [
    # "tests/sample-docs/CustomerChurn_Jan2025.xlsx",
    # "tests/sample-docs/PureTable_CustomerChurn_Jan2025.pdf",
    # "tests/sample-docs/SS_CustomerChurn_Jan2025.pdf",
]


async def _run_seeding(comparison_files: list[str]) -> None:
    """Background coroutine: ingest + embed each seed file if not already EMBEDDED."""
    from pipeline import ingest_file_direct, process_by_doc_id

    for file_path_str in comparison_files:
        path = Path(file_path_str)
        if not path.exists():
            logger.warning(f"Seed file not found: {file_path_str}")
            continue
        try:
            file_bytes = path.read_bytes()
            content_hash = hashlib.sha256(file_bytes).hexdigest()
            existing = get_documents_col().find_one(
                {"content_hash": content_hash, "status": "EMBEDDED"}, {"doc_id": 1}
            )
            if existing:
                logger.info(f"Seed skip (already embedded): {path.name}")
                continue
            logger.info(f"Seed start: {path.name}")
            doc_id, file_bytes, filename, original_format, format_provenance = \
                await asyncio.to_thread(ingest_file_direct, path)
            await asyncio.to_thread(process_by_doc_id, doc_id, False, True)
            # Also run MarkItDown pipeline for comparison (only for Office files)
            try:
                from markitdown_pipeline import run_markitdown_pipeline, should_process_with_markitdown
                if should_process_with_markitdown(filename, original_format):
                    await asyncio.to_thread(
                        run_markitdown_pipeline,
                        file_bytes, filename, doc_id, original_format, format_provenance,
                    )
            except Exception as e:
                logger.warning(f"Seed MarkItDown failed for {path.name}: {e}")
            logger.info(f"Seed complete: {path.name}")
        except Exception as e:
            logger.error(f"Seed failed for {path.name}: {e}")


@app.on_event("startup")
async def seed_comparison_files() -> None:
    """
    Auto-ingest and embed comparison files if not already EMBEDDED.
    File paths from SEED_FILES env var (comma-separated).
    SEED_FILES= (empty string) → skip seeding entirely.
    Runs in background — does not block service startup or health check.
    """
    seed_env = os.getenv("SEED_FILES")

    if seed_env is not None and seed_env.strip() == "":
        logger.info("Seed: SEED_FILES is empty — skipping seeding")
        return

    if seed_env:
        comparison_files = [p.strip() for p in seed_env.split(",") if p.strip()]
    else:
        comparison_files = _DEFAULT_SEED_FILES

    asyncio.create_task(_run_seeding(comparison_files))
