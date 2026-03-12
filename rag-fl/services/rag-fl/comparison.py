"""
services/rag-fl/comparison.py
Comparison API — PyMuPDF vs MarkItDown embedding quality.

Endpoints:
  GET  /comparison/documents      → list EMBEDDED docs + chunk counts per method
  GET  /comparison/{doc_id}       → side-by-side chunks for one document
  POST /comparison/search         → same query against both method chunk sets
"""
import logging
import os

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from shared.utils.mongo_client import (
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
)
from shared.utils.vector_search import vector_search

logger = logging.getLogger("ragfl.comparison")

router = APIRouter(prefix="/comparison", tags=["comparison"])

# ── Business rules (mirrors markitdown_pipeline.py) ──────────────────────────

_BASELINE_FILENAMES: set[str] = {
    "CustomerChurn_Jan2025.xlsx",
    "PureTable_CustomerChurn_Jan2025.pdf",
    "SS_CustomerChurn_Jan2025.pdf",
}

_NO_COMPARISON_FORMATS: set[str] = {"pdf", "jpeg", "jpg", "png", "gif", "bmp", "tiff"}


def get_method_a_label(original_format: str) -> str:
    """Short label for Method A (existing pipeline)."""
    return {
        "xlsx": "openpyxl",
        "xls":  "openpyxl",
        "docx": "Gotenberg → PDF",
        "pptx": "Gotenberg → PDF",
        "csv":  "pandas/csv",
        "yaml": "PyYAML",
        "yml":  "PyYAML",
    }.get(original_format, "Current Pipeline")


def get_method_b_label(original_format: str) -> str:
    """Short label for Method B (MarkItDown) that describes what it's reading."""
    return {
        "xlsx": "Direct Excel Read",
        "xls":  "Direct Excel Read",
        "docx": "Direct DOCX Read",
        "pptx": "Direct PPTX Read",
        "csv":  "Direct CSV Read",
        "yaml": "Direct YAML Read",
        "yml":  "Direct YAML Read",
    }.get(original_format, "MarkItDown")


def _add_embedding_dims(chunks: list[dict]) -> list[dict]:
    """Pop embedding vector, replace with dims count."""
    for c in chunks:
        emb = c.pop("embedding", None)
        c["embedding_dims"] = len(emb) if emb else 0
    return chunks

# ── MongoDB filter helpers ─────────────────────────────────────────────────────
# "existing" = current pipeline (Gotenberg → PDF → PyMuPDF for DOCX/PPTX, openpyxl for Excel).
# Legacy chunks stored with "pymupdf" before the rename are also included for backward compat.
_PYMUPDF_FILTER: dict = {
    "$or": [
        {"processing_method": "existing"},
        {"processing_method": "pymupdf"},   # legacy value pre-rename
        {"processing_method": {"$exists": False}},
        {"processing_method": None},
    ]
}

_CHUNK_PROJ = {
    "_id": 0,
    "chunk_id": 1,
    "chunk_type": 1,
    "chunk_text": 1,
    "page_number": 1,
    "section_title": 1,
    "chunk_index": 1,
    "format_provenance": 1,
    "gcs_image_path": 1,
    "processing_method": 1,
    "bounding_box": 1,
    "embedding_model": 1,
    "embedding": 1,          # kept for dims; stripped before response
}


# ── Request models ─────────────────────────────────────────────────────────────

class ComparisonSearchRequest(BaseModel):
    query: str
    doc_id: Optional[str] = None
    top_k: int = 5


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/documents")
async def list_comparison_documents():
    """List all EMBEDDED documents with chunk counts for each method."""
    docs = list(
        get_documents_col()
        .find(
            {"status": "EMBEDDED"},
            {"_id": 0, "doc_id": 1, "filename": 1, "original_format": 1,
             "total_pages": 1, "report_period": 1},
        )
        .sort("created_at", -1)
    )

    col = get_embeddings_col()
    result = []
    for doc in docs:
        did = doc["doc_id"]
        fmt = doc.get("original_format", "")
        fname = doc.get("filename", "")

        # Baseline and no-comparison formats never show method comparison
        is_baseline = fname in _BASELINE_FILENAMES
        is_blocked = fmt in _NO_COMPARISON_FORMATS

        pymupdf_n = col.count_documents({"doc_id": did, **_PYMUPDF_FILTER})
        mkd_n = col.count_documents({"doc_id": did, "processing_method": "markitdown"})

        result.append({
            **doc,
            "pymupdf_chunks": pymupdf_n,
            "markitdown_chunks": mkd_n,
            # both_ready = False for baseline files and PDF/image formats
            "both_ready": (not is_baseline) and (not is_blocked) and pymupdf_n > 0 and mkd_n > 0,
            "method_a_label": get_method_a_label(fmt),
            "method_b_label": get_method_b_label(fmt),
            "is_baseline": is_baseline,
            "comparison_supported": (not is_baseline) and (not is_blocked),
        })

    return {"documents": result, "count": len(result)}


@router.get("/{doc_id}")
async def get_comparison(doc_id: str, limit: int = Query(50)):
    """Return both method chunk sets for one document."""
    doc = get_documents_col().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    fname = doc.get("filename", "")
    fmt = doc.get("original_format", "")

    if fname in _BASELINE_FILENAMES:
        raise HTTPException(
            status_code=400,
            detail=f"'{fname}' is a baseline file — use format comparison, not method comparison.",
        )
    if fmt in _NO_COMPARISON_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"{fmt.upper()} files use {get_method_a_label(fmt)} only — no MarkItDown comparison.",
        )

    col = get_embeddings_col()

    pymupdf_chunks = list(
        col.find({"doc_id": doc_id, **_PYMUPDF_FILTER}, _CHUNK_PROJ)
        .sort([("page_number", 1), ("chunk_index", 1)])
        .limit(limit)
    )
    mkd_chunks = list(
        col.find({"doc_id": doc_id, "processing_method": "markitdown"}, _CHUNK_PROJ)
        .sort([("page_number", 1), ("chunk_index", 1)])
        .limit(limit)
    )

    pymupdf_total = col.count_documents({"doc_id": doc_id, **_PYMUPDF_FILTER})
    mkd_total = col.count_documents({"doc_id": doc_id, "processing_method": "markitdown"})

    pymupdf_chunks = _add_embedding_dims(pymupdf_chunks)
    mkd_chunks = _add_embedding_dims(mkd_chunks)

    return {
        "doc_id": doc_id,
        "filename": fname,
        "original_format": fmt,
        "method_a_label": get_method_a_label(fmt),
        "method_b_label": get_method_b_label(fmt),
        "pymupdf": {
            "total_chunks": pymupdf_total,
            "chunks_shown": len(pymupdf_chunks),
            "type_breakdown": _type_breakdown(pymupdf_chunks),
            "chunks": pymupdf_chunks,
        },
        "markitdown": {
            "total_chunks": mkd_total,
            "chunks_shown": len(mkd_chunks),
            "type_breakdown": _type_breakdown(mkd_chunks),
            "chunks": mkd_chunks,
        },
    }


@router.post("/search")
async def comparison_search(req: ComparisonSearchRequest):
    """Run the same query against PyMuPDF and MarkItDown chunk sets."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    query_vec = _embed_query(req.query)
    col = get_embeddings_col()

    base: dict = {}
    if req.doc_id:
        base["doc_id"] = req.doc_id

    pymupdf_results = _search_method(col, {**base, **_PYMUPDF_FILTER}, query_vec, req.top_k)
    mkd_results = _search_method(
        col, {**base, "processing_method": "markitdown"}, query_vec, req.top_k
    )

    # Attach filenames when not scoped to one doc
    if not req.doc_id:
        doc_ids = {r["doc_id"] for r in pymupdf_results + mkd_results}
        docs_map = {
            d["doc_id"]: d["filename"]
            for d in get_documents_col().find(
                {"doc_id": {"$in": list(doc_ids)}}, {"doc_id": 1, "filename": 1}
            )
        }
        for r in pymupdf_results + mkd_results:
            r["filename"] = docs_map.get(r["doc_id"], "")

    return {
        "query": req.query,
        "doc_id": req.doc_id,
        "pymupdf_results": pymupdf_results,
        "markitdown_results": mkd_results,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _embed_query(query: str) -> list[float]:
    """Embed a search query with RETRIEVAL_QUERY task type."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY", ""))
    model = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    try:
        result = client.models.embed_content(
            model=model,
            contents=query,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        return result.embeddings[0].values
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query embedding failed: {exc}")


def _search_method(col, query_filter: dict, query_vec: list[float], top_k: int) -> list[dict]:
    """In-memory cosine similarity search within a filtered chunk set."""
    proj = {
        "_id": 0, "chunk_id": 1, "chunk_text": 1, "chunk_type": 1,
        "page_number": 1, "section_title": 1, "doc_id": 1,
        "format_provenance": 1, "embedding": 1, "processing_method": 1,
    }
    chunks = list(col.find(query_filter, proj))
    q = np.array(query_vec, dtype=np.float32)
    scored = []
    for c in chunks:
        emb = c.pop("embedding", None)
        if emb:
            e = np.array(emb, dtype=np.float32)
            denom = float(np.linalg.norm(q) * np.linalg.norm(e))
            score = float(np.dot(q, e) / denom) if denom > 0 else 0.0
            scored.append({**c, "score": round(score, 4)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def _type_breakdown(chunks: list[dict]) -> dict:
    breakdown: dict = {}
    for c in chunks:
        t = c.get("chunk_type", "unknown")
        breakdown[t] = breakdown.get(t, 0) + 1
    return breakdown
