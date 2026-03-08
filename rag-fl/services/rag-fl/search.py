"""
services/rag-fl/search.py
Phase 6 — Search & Retrieval API.

Endpoints:
  POST /search                    → global search with filters, Redis 1hr cache
  POST /search/within/{doc_id}    → document-scoped search (upgrades Phase 4 version)
  GET  /document/{doc_id}/summary → doc stats + per-page-type breakdown

Filters (POST /search):
  doc_ids       → restrict to explicit list of doc_ids
  format        → "pdf" | "xlsx" | "yaml" | etc. — queries documents{} first
  report_period → "2025-01" (YYYY-MM) — queries documents{} first
  report_series → e.g. "monthly_churn" — queries documents{} first

Cache:
  Backend: Redis, TTL 1hr
  Key: sha256(query + doc_id + filters + include_multimodal)
  Failures silently degrade to cache-miss (non-fatal).

Response shape (ARCHITECTURE.md / PHASES.md §Phase 6):
  {
    "answer_chunks": [{chunk_id, chunk_text, chunk_type, score, page_number, doc_id, ...}],
    "citations":     [{label, page_number, doc_id, filename, chunk_type, deep_link, chunk_id}],
    "query_metadata": {docs_searched, response_time_ms, top_k, filters_applied, cached}
  }

CRITICAL: query embedding MUST use RETRIEVAL_QUERY task type — asymmetric from
RETRIEVAL_DOCUMENT used at storage time (Phase 3). Never swap these.
"""
import hashlib
import json
import logging
import os
import time
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from citation import build_deep_link, build_label
from shared.utils.mongo_client import (
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
    page_profiles as get_profiles_col,
)
from shared.utils.vector_search import vector_search

logger = logging.getLogger("ragfl.search")

router = APIRouter()

SEARCH_CACHE_TTL = 3600  # 1 hour


# ── Redis client ──────────────────────────────────────────────────────────────

_redis_client: Optional[redis_lib.Redis] = None


def _get_redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://redis:6379")
        _redis_client = redis_lib.from_url(url, decode_responses=True)
    return _redis_client


# ── Query embedding ───────────────────────────────────────────────────────────

def _embed_query(text: str) -> list[float]:
    """
    Embed a user query with RETRIEVAL_QUERY task type.
    CRITICAL: this is asymmetric — always RETRIEVAL_QUERY here,
              always RETRIEVAL_DOCUMENT at storage time (Phase 3).
    """
    from google import genai
    from google.genai import types

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    client = genai.Client(api_key=api_key)
    result = client.models.embed_content(
        model=os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001"),
        contents=text,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )
    return result.embeddings[0].values


# ── Redis cache helpers ───────────────────────────────────────────────────────

def _cache_key(
    query: str,
    filters: dict,
    doc_id: Optional[str] = None,
    include_multimodal: bool = True,
) -> str:
    payload = json.dumps(
        {"query": query, "doc_id": doc_id, "filters": filters, "include_multimodal": include_multimodal},
        sort_keys=True,
    )
    return "search:" + hashlib.sha256(payload.encode()).hexdigest()


def _get_cached(key: str) -> Optional[dict]:
    try:
        raw = _get_redis().get(key)
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Redis cache read failed: {e}")
    return None


def _set_cached(key: str, data: dict) -> None:
    try:
        _get_redis().setex(key, SEARCH_CACHE_TTL, json.dumps(data))
    except Exception as e:
        logger.warning(f"Redis cache write failed: {e}")


# ── Pydantic models ───────────────────────────────────────────────────────────

class SearchFilters(BaseModel):
    doc_ids: Optional[list[str]] = None
    format: Optional[str] = None          # "pdf" | "xlsx" | "yaml" | ...
    report_period: Optional[str] = None   # "2025-01" (YYYY-MM)
    report_series: Optional[str] = None   # e.g. "monthly_churn"


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: Optional[SearchFilters] = None
    include_multimodal: bool = True


class WithinSearchRequest(BaseModel):
    query: str
    top_k: int = 5


# ── Filter helpers ────────────────────────────────────────────────────────────

def _resolve_doc_filter(filters: Optional[SearchFilters]) -> Optional[list[str]]:
    """
    Translate document-level filters (format, report_period, report_series)
    into a list of matching doc_ids by querying documents{}.
    Returns None when no doc-level constraints are set (search all docs).
    """
    if not filters:
        return None
    doc_query: dict = {}
    if filters.format:
        doc_query["original_format"] = filters.format
    if filters.report_period:
        doc_query["report_period"] = filters.report_period
    if filters.report_series:
        doc_query["report_series"] = filters.report_series
    if not doc_query:
        return None
    matched = list(get_documents_col().find(doc_query, {"doc_id": 1}))
    return [d["doc_id"] for d in matched]


def _build_chunk_filter(
    filters: Optional[SearchFilters],
    resolved_doc_ids: Optional[list[str]],
    include_multimodal: bool,
) -> dict:
    """
    Build the MongoDB filter dict passed to vector_search().
    Intersects explicit doc_ids with doc-level-resolved doc_ids.
    Optionally excludes multimodal chunks.
    """
    chunk_filter: dict = {}

    # Collect and intersect all applicable doc_id sets
    all_doc_ids: Optional[set] = None
    if filters and filters.doc_ids:
        all_doc_ids = set(filters.doc_ids)
    if resolved_doc_ids is not None:
        if all_doc_ids is not None:
            all_doc_ids &= set(resolved_doc_ids)
        else:
            all_doc_ids = set(resolved_doc_ids)
    if all_doc_ids is not None:
        chunk_filter["doc_id"] = {"$in": list(all_doc_ids)}

    if not include_multimodal:
        chunk_filter["chunk_type"] = {"$in": ["text", "table"]}

    return chunk_filter


def _count_docs_searched(chunk_filter: dict) -> int:
    """Count how many embedded documents fell within the search scope."""
    if "doc_id" in chunk_filter:
        return len(chunk_filter["doc_id"]["$in"])
    return get_documents_col().count_documents({"status": "EMBEDDED"})


# ── Result formatting ─────────────────────────────────────────────────────────

def _format_results(raw_results: list[dict], docs_map: dict) -> tuple[list, list]:
    """
    Convert raw vector_search results to (answer_chunks, citations).
    Calls build_label / build_deep_link directly — no HTTP round-trip.
    """
    answer_chunks = []
    citations = []
    for r in raw_results:
        doc_id = r.get("doc_id", "")
        doc = docs_map.get(doc_id, {"filename": "Unknown", "original_format": "pdf"})
        chunk_text = r.get("chunk_text", "") or ""

        answer_chunks.append({
            "chunk_id": r.get("chunk_id"),
            "chunk_type": r.get("chunk_type"),
            "chunk_text": chunk_text[:300],
            "page_number": r.get("page_number"),
            "doc_id": doc_id,
            "score": round(float(r.get("score", 0)), 4),
            "gcs_image_path": r.get("gcs_image_path"),
            "section_title": r.get("section_title", ""),
        })

        citations.append({
            "label": build_label(r, doc),
            "page_number": r.get("page_number"),
            "doc_id": doc_id,
            "filename": doc.get("filename", ""),
            "chunk_type": r.get("chunk_type"),
            "deep_link": build_deep_link(r, doc_id),
            "chunk_id": r.get("chunk_id"),
        })

    return answer_chunks, citations


# ── POST /search ──────────────────────────────────────────────────────────────

@router.post("/search")
async def search(req: SearchRequest):
    """
    Global semantic search across all (or filtered) documents.

    Filter precedence:
      1. filters.doc_ids → restrict to these doc_ids directly
      2. filters.format / report_period / report_series → resolve matching doc_ids
         from documents{} collection, then intersect with filters.doc_ids if both set
      3. include_multimodal=false → exclude chunk_type=multimodal from candidates

    Cache: Redis 1hr, key=sha256(query + filters + include_multimodal).
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    filters_dict = req.filters.model_dump() if req.filters else {}
    key = _cache_key(req.query, filters_dict, include_multimodal=req.include_multimodal)
    cached = _get_cached(key)
    if cached:
        cached["query_metadata"]["cached"] = True
        logger.info(f"search: cache hit for query={req.query!r}")
        return cached

    t0 = time.monotonic()

    resolved_doc_ids = _resolve_doc_filter(req.filters)
    chunk_filter = _build_chunk_filter(req.filters, resolved_doc_ids, req.include_multimodal)
    docs_searched = _count_docs_searched(chunk_filter)

    try:
        query_vector = _embed_query(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    raw_results = vector_search(
        get_embeddings_col(),
        query_vector,
        top_k=req.top_k,
        filter_query=chunk_filter or None,
    )

    doc_ids_in_results = list({r["doc_id"] for r in raw_results})
    docs_map = {
        d["doc_id"]: d
        for d in get_documents_col().find(
            {"doc_id": {"$in": doc_ids_in_results}},
            {"doc_id": 1, "filename": 1, "original_format": 1},
        )
    }

    answer_chunks, citations = _format_results(raw_results, docs_map)
    elapsed_ms = round((time.monotonic() - t0) * 1000)

    response = {
        "query": req.query,
        "answer_chunks": answer_chunks,
        "citations": citations,
        "query_metadata": {
            "docs_searched": docs_searched,
            "response_time_ms": elapsed_ms,
            "top_k": req.top_k,
            "filters_applied": bool(chunk_filter),
            "cached": False,
        },
    }
    _set_cached(key, response)
    logger.info(
        f"search: query={req.query!r} → {len(answer_chunks)} results "
        f"from {docs_searched} docs in {elapsed_ms}ms"
    )
    return response


# ── POST /search/within/{doc_id} ──────────────────────────────────────────────

@router.post("/search/within/{doc_id}")
async def search_within_document(doc_id: str, req: WithinSearchRequest):
    """
    Document-scoped semantic search with Redis cache and full citation labels.
    Returns unified response shape plus `results` alias for Phase 4 UI compatibility.
    """
    doc = get_documents_col().find_one(
        {"doc_id": doc_id},
        {"doc_id": 1, "filename": 1, "original_format": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    key = _cache_key(req.query, {}, doc_id=doc_id)
    cached = _get_cached(key)
    if cached:
        cached["query_metadata"]["cached"] = True
        logger.info(f"search/within: cache hit for doc={doc_id} query={req.query!r}")
        return cached

    t0 = time.monotonic()

    try:
        query_vector = _embed_query(req.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")

    raw_results = vector_search(
        get_embeddings_col(),
        query_vector,
        top_k=req.top_k,
        filter_query={"doc_id": doc_id},
    )

    docs_map = {doc_id: doc}
    answer_chunks, citations = _format_results(raw_results, docs_map)
    elapsed_ms = round((time.monotonic() - t0) * 1000)

    response = {
        "doc_id": doc_id,
        "filename": doc.get("filename", ""),
        "query": req.query,
        "answer_chunks": answer_chunks,
        "results": answer_chunks,   # backward compat — Phase 4 UI reads .results
        "citations": citations,
        "count": len(answer_chunks),
        "query_metadata": {
            "docs_searched": 1,
            "response_time_ms": elapsed_ms,
            "top_k": req.top_k,
            "filters_applied": True,
            "cached": False,
        },
    }
    _set_cached(key, response)
    logger.info(
        f"search/within: doc={doc_id} query={req.query!r} "
        f"→ {len(answer_chunks)} results in {elapsed_ms}ms"
    )
    return response


# ── GET /document/{doc_id}/summary ───────────────────────────────────────────

@router.get("/document/{doc_id}/summary")
async def document_summary(doc_id: str):
    """
    Summary statistics for a document:
    - Metadata (filename, format, status, report_period, report_series)
    - Total chunks + embedding confirmation
    - Per-page-type breakdown from page_profiles
    """
    doc = get_documents_col().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    for ts in ("created_at", "updated_at", "upload_timestamp",
               "report_period_start", "report_period_end"):
        if doc.get(ts):
            doc[ts] = doc[ts].isoformat()

    profiles = list(
        get_profiles_col().find({"doc_id": doc_id}, {"page_type": 1, "_id": 0})
    )
    type_breakdown: dict = {}
    for p in profiles:
        pt = p.get("page_type", "unknown")
        type_breakdown[pt] = type_breakdown.get(pt, 0) + 1

    chunk_count = get_embeddings_col().count_documents({"doc_id": doc_id})

    return {
        "doc_id": doc_id,
        "filename": doc.get("filename"),
        "original_format": doc.get("original_format"),
        "status": doc.get("status"),
        "total_pages": doc.get("total_pages"),
        "chunk_count": chunk_count,
        "embedding_dims": 768,
        "page_type_breakdown": type_breakdown,
        "report_period": doc.get("report_period"),
        "report_series": doc.get("report_series"),
        "period_confidence": doc.get("period_confidence"),
        "report_frequency": doc.get("report_frequency"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
