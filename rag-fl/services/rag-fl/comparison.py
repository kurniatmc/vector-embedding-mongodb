"""
services/rag-fl/comparison.py (chunks viewer)
Document Chunks Viewer API — Browse extracted chunks per document.

Endpoints:
  GET  /comparison/documents      → list all EMBEDDED documents
  GET  /comparison/{doc_id}       → view all chunks for one document
  POST /comparison/search         → search across chunks

Processing methods (informational only, no comparison):
  - XLSX/CSV: MarkItDown (tables) + Vision (charts)
  - DOCX/PPTX: Gotenberg → PDF → Vision
  - PDF: PyMuPDF + Vision
  - Images: Vision (image analysis)
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

logger = logging.getLogger("ragfl.comparison")

router = APIRouter(prefix="/comparison", tags=["comparison"])

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


class ComparisonSearchRequest(BaseModel):
    query: str
    doc_id: Optional[str] = None
    top_k: int = 5


def _get_processing_info(original_format: str) -> str:
    """Return processing method description for UI display."""
    if original_format in ("xlsx", "xls", "csv"):
        return "MarkItDown + Vision (charts)"
    elif original_format in ("docx", "pptx"):
        return "Gotenberg → PDF → Vision"
    elif original_format == "pdf":
        return "PyMuPDF + Vision"
    elif original_format in ("jpeg", "jpg", "png", "bmp", "tiff", "gif", "webp"):
        return "Vision (image analysis)"
    elif original_format in ("yaml", "yml"):
        return "YAML parser"
    else:
        return "Standard pipeline"


def _add_embedding_dims(chunks: list[dict]) -> list[dict]:
    """Pop embedding vector, replace with dims count."""
    for c in chunks:
        emb = c.pop("embedding", None)
        c["embedding_dims"] = len(emb) if emb else 0
    return chunks


def _type_breakdown(chunks: list[dict]) -> dict:
    breakdown: dict = {}
    for c in chunks:
        t = c.get("chunk_type", "unknown")
        breakdown[t] = breakdown.get(t, 0) + 1
    return breakdown


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/documents")
async def list_comparison_documents():
    """List all EMBEDDED documents with total chunk counts."""
    docs = list(
        get_documents_col()
        .find(
            {"status": "EMBEDDED"},
            {
                "_id": 0,
                "doc_id": 1,
                "filename": 1,
                "original_format": 1,
                "total_pages": 1,
                "report_period": 1,
                "created_at": 1,
            },
        )
        .sort("created_at", -1)
    )

    col = get_embeddings_col()
    result = []
    for doc in docs:
        did = doc["doc_id"]
        total_chunks = col.count_documents({"doc_id": did})

        result.append({
            **doc,
            "total_chunks": total_chunks,
            "processing_info": _get_processing_info(doc.get("original_format", "")),
        })

    return {"documents": result, "count": len(result)}


@router.get("/{doc_id}")
async def get_comparison(doc_id: str, limit: int = Query(50)):
    """Return all chunks for one document."""
    doc = get_documents_col().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    fname = doc.get("filename", "")
    fmt = doc.get("original_format", "")

    col = get_embeddings_col()

    chunks = list(
        col.find({"doc_id": doc_id}, _CHUNK_PROJ)
        .sort([("page_number", 1), ("chunk_index", 1)])
        .limit(limit)
    )

    total_chunks = col.count_documents({"doc_id": doc_id})
    chunks = _add_embedding_dims(chunks)

    return {
        "doc_id": doc_id,
        "filename": fname,
        "original_format": fmt,
        "processing_info": _get_processing_info(fmt),
        "total_chunks": total_chunks,
        "chunks_shown": len(chunks),
        "type_breakdown": _type_breakdown(chunks),
        "chunks": chunks,
    }


@router.post("/search")
async def comparison_search(req: ComparisonSearchRequest):
    """Search across all chunks (unified, no method separation)."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    query_vec = _embed_query(req.query)
    col = get_embeddings_col()

    base_filter: dict = {}
    if req.doc_id:
        base_filter["doc_id"] = req.doc_id

    results = _search_method(col, base_filter, query_vec, req.top_k)

    # Attach filenames when not scoped to one doc
    if not req.doc_id:
        doc_ids = {r["doc_id"] for r in results}
        docs_map = {
            d["doc_id"]: d["filename"]
            for d in get_documents_col().find(
                {"doc_id": {"$in": list(doc_ids)}}, {"doc_id": 1, "filename": 1}
            )
        }
        for r in results:
            r["filename"] = docs_map.get(r["doc_id"], "")

    return {
        "query": req.query,
        "doc_id": req.doc_id,
        "results": results,
        "count": len(results),
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
