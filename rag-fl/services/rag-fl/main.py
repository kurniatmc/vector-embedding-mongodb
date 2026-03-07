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
import logging
import os
from datetime import datetime
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

# Allow Next.js UI (localhost:3001) to call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ───────────────────────────────────────────────────

class ProcessRequest(BaseModel):
    doc_id: str
    classify_only: bool = False


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
    try:
        result = process_by_doc_id(req.doc_id, classify_only=req.classify_only, auto_confirm=True)
        return ProcessResponse(
            doc_id=req.doc_id,
            filename=doc.get("filename", ""),
            status="EMBEDDED" if not req.classify_only else "UPLOADED",
            message=(
                f"Pipeline complete: {result.get('total_chunks', 0)} chunks, "
                f"{result.get('gemini_calls', 0)} Gemini calls"
            ),
        )
    except Exception as e:
        logger.error(f"Pipeline failed for {req.doc_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")


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
async def get_page_image(doc_id: str, page_number: int):
    """Proxy a page PNG from fake-gcs to the browser. Avoids CORS issues."""
    from shared.utils.gcs_client import download_bytes, blob_exists

    gcs_path = f"{doc_id}.{page_number}"
    if not blob_exists(gcs_path):
        raise HTTPException(status_code=404, detail=f"Image not found: {gcs_path}")
    try:
        image_bytes = download_bytes(gcs_path)
        return Response(content=image_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch image: {e}")


# ── Config endpoint (Phase 4 top bar — FORCE_MIXED_MODE indicator) ────────────

@app.get("/config")
async def get_config():
    """Return relevant runtime configuration for the UI."""
    return {
        "force_mixed_mode": os.getenv("FORCE_MIXED_MODE", "false"),
        "environment": os.getenv("ENVIRONMENT", "development"),
        "dry_run_threshold": int(os.getenv("DRY_RUN_THRESHOLD", "10")),
    }
