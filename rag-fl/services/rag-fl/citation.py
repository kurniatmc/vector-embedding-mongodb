"""
services/rag-fl/citation.py
Phase 5 — Citation Engine & Provenance API.

Builds human-readable citation labels from chunk + document metadata.
Merges adjacent pages (±1) into a single citation.
Caches results in MongoDB citation_cache{} with 1-hour TTL.

Label formats (from ARCHITECTURE.md):
  PDF text:       "{doc_name}, Page N, Section {section_title}"
  PDF table:      "{doc_name}, Page N, Table {n}: {col2} by {col1}"
  PDF multimodal: "{doc_name}, Page N, Figure: {first 10 words of Gemini desc}"
  Excel:          "{filename}, Sheet: {sheet_name}, Rows {row_start}–{row_end}"
  YAML:           "{filename}, Key: {key_path}"
"""
import hashlib
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shared.utils.mongo_client import (
    citation_cache as get_cache_col,
    doc_embeddings as get_embeddings_col,
    documents as get_documents_col,
    page_profiles as get_profiles_col,
)

logger = logging.getLogger("ragfl.citation")

router = APIRouter()

CITATION_TTL_HOURS = 1

# Base URL for deep links — browser-side, so localhost ports
_RAG_FL_BASE = os.getenv("CITATION_RAG_FL_BASE", "http://localhost:8004")
_UI_BASE = os.getenv("CITATION_UI_BASE", "http://localhost:3001")


# ── Pydantic models ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    chunk_ids: list[str]


# ── Display name helper ───────────────────────────────────────────────────────

def _doc_display_name(filename: str, original_format: str) -> str:
    """
    Human-readable doc name for use in citation labels.
    - Excel/YAML: keep full filename (extension is meaningful)
    - PDF/other:  strip extension, replace underscores with spaces
    """
    if original_format in ("xlsx", "xls", "yaml", "yml"):
        return filename
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    return name.replace("_", " ")


# ── Gemini description cleaner ────────────────────────────────────────────────

_GEMINI_SKIP_PATTERNS = re.compile(
    r"^(here'?s?\s+(a\s+)?comprehensive|here\s+is\s+a|overall\s+(content|structure))",
    re.IGNORECASE,
)


def _gemini_snippet(chunk_text: str, word_count: int = 10) -> str:
    """
    First N meaningful words from a Gemini Vision description.
    Skips the boilerplate opener ("Here's a comprehensive description...")
    and markdown section headers. Returns plain text.
    """
    lines = chunk_text.strip().split("\n")
    collected: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip opener and generic section headings
        if _GEMINI_SKIP_PATTERNS.match(stripped):
            continue
        # Strip markdown: bold (**), italic (*), headers (#), bullets (*, -)
        clean = re.sub(r"\*+", "", stripped)
        clean = re.sub(r"^#+\s*", "", clean)
        clean = re.sub(r"^[-•]\s*", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean:
            continue
        collected.append(clean)
        if len(" ".join(collected).split()) >= word_count:
            break

    full = " ".join(collected)
    words = full.split()[:word_count]
    return " ".join(words)


# ── Table helpers ─────────────────────────────────────────────────────────────

def _extract_table_cols(chunk_text: str) -> list[str]:
    """Parse column headers from first row of a Markdown table."""
    for line in chunk_text.strip().split("\n"):
        if "|" in line and not re.match(r"^\|[-\s|]+\|$", line.strip()):
            return [c.strip() for c in line.split("|") if c.strip()]
    return []


def _table_number(doc_id: str, page_number: int, chunk_index: int) -> int:
    """1-based sequential table number within the document."""
    count = get_embeddings_col().count_documents({
        "doc_id": doc_id,
        "chunk_type": "table",
        "$or": [
            {"page_number": {"$lt": page_number}},
            {"page_number": page_number, "chunk_index": {"$lt": chunk_index}},
        ],
    })
    return count + 1


# ── Core label builder ────────────────────────────────────────────────────────

def build_label(
    chunk: dict,
    doc: dict,
    table_n: Optional[int] = None,
) -> str:
    """
    Build the human-readable citation label.
    All format decisions follow ARCHITECTURE.md §Citation Format.
    """
    filename = doc.get("filename", "")
    orig_fmt = (chunk.get("format_provenance") or {}).get("original_format", "pdf")
    doc_name = _doc_display_name(filename, orig_fmt)
    page_num = chunk.get("page_number", 1)
    chunk_type = chunk.get("chunk_type", "text")
    section_title = (chunk.get("section_title") or "").strip()
    fp = chunk.get("format_provenance") or {}

    # ── Excel ──────────────────────────────────────────────────────────────────
    if orig_fmt in ("xlsx", "xls"):
        sheet = fp.get("sheet_name", "Sheet1")
        row_start = fp.get("row_start", 1)
        row_end = fp.get("row_end", row_start)
        return f"{doc_name}, Sheet: {sheet}, Rows {row_start}–{row_end}"

    # ── YAML ───────────────────────────────────────────────────────────────────
    if orig_fmt in ("yaml", "yml"):
        key_path = fp.get("key_path", "")
        return (
            f"{doc_name}, Key: {key_path}"
            if key_path
            else f"{doc_name}, Page {page_num}"
        )

    # ── Multimodal ─────────────────────────────────────────────────────────────
    if chunk_type == "multimodal":
        snippet = _gemini_snippet(chunk.get("chunk_text", ""), word_count=10)
        return f"{doc_name}, Page {page_num}, Figure: {snippet}"

    # ── Table ──────────────────────────────────────────────────────────────────
    if chunk_type == "table":
        n = table_n if table_n is not None else 1
        cols = _extract_table_cols(chunk.get("chunk_text", ""))
        if len(cols) >= 2:
            title = f"{cols[1]} by {cols[0]}"
        elif cols:
            title = cols[0]
        else:
            title = "Data"
        return f"{doc_name}, Page {page_num}, Table {n}: {title}"

    # ── Text (default) ─────────────────────────────────────────────────────────
    if section_title:
        return f"{doc_name}, Page {page_num}, Section {section_title}"
    return f"{doc_name}, Page {page_num}"


# ── Deep link builder ─────────────────────────────────────────────────────────

def build_deep_link(chunk: dict, doc_id: str) -> str:
    """
    Deep link URLs:
      multimodal → image proxy (serves the PNG directly)
      text/table → UI link with doc+page anchor
    """
    page_num = chunk.get("page_number", 1)
    if chunk.get("chunk_type") == "multimodal" and chunk.get("gcs_image_path"):
        return f"{_RAG_FL_BASE}/image/{doc_id}/{page_num}"
    return f"{_UI_BASE}/?doc_id={doc_id}&page={page_num}"


# ── Adjacent page merging ─────────────────────────────────────────────────────

def _merge_adjacent(groups: list[dict]) -> list[dict]:
    """
    Merge groups from the same document where consecutive page numbers differ by ≤ 1.
    Input must be sorted by (doc_id, page_number).
    """
    if not groups:
        return []
    merged = [groups[0].copy()]
    for g in groups[1:]:
        last = merged[-1]
        if g["doc_id"] == last["doc_id"] and (g["page_number"] - last["page_end"]) <= 1:
            last["page_end"] = g["page_number"]
            last["chunks"].extend(g["chunks"])
        else:
            merged.append(g.copy())
    return merged


# ── Citation cache ────────────────────────────────────────────────────────────

def _ensure_ttl_index() -> None:
    """
    Ensure a TTL index exists on citation_cache.expires_at.
    Silently accepts IndexOptionsConflict (code 85) — the index already exists
    under a different name created by mongo-init, which is fine.
    """
    try:
        get_cache_col().create_index("expires_at", expireAfterSeconds=0)
        logger.info("citation_cache: TTL index created on expires_at")
    except Exception as e:
        if getattr(e, "code", None) == 85 or "already exists" in str(e).lower():
            pass  # TTL index already present — nothing to do
        else:
            logger.warning(f"citation_cache: could not create TTL index: {e}")


def _cache_key(chunk_ids: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(chunk_ids)).encode()).hexdigest()


def _get_cached(key: str) -> Optional[list]:
    doc = get_cache_col().find_one(
        {"cache_key": key, "expires_at": {"$gt": datetime.utcnow()}}
    )
    return doc["citations"] if doc else None


def _set_cached(key: str, chunk_ids: list[str], citations: list) -> None:
    get_cache_col().replace_one(
        {"cache_key": key},
        {
            "cache_key": key,
            "chunk_ids": chunk_ids,
            "citations": citations,
            "expires_at": datetime.utcnow() + timedelta(hours=CITATION_TTL_HOURS),
        },
        upsert=True,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/citations/generate")
async def generate_citations(req: GenerateRequest):
    """
    Build citations for a list of chunk_ids.
    Adjacent pages (±1) within the same document are merged into one citation.
    Results cached in MongoDB citation_cache{} for 1 hour.
    """
    if not req.chunk_ids:
        raise HTTPException(status_code=400, detail="chunk_ids must not be empty")

    _ensure_ttl_index()

    key = _cache_key(req.chunk_ids)
    cached = _get_cached(key)
    if cached is not None:
        logger.info(f"citations: cache hit for {len(req.chunk_ids)} chunk_ids")
        return {"citations": cached, "count": len(cached), "cached": True}

    # Fetch chunks (exclude heavy embedding vector)
    chunks = list(get_embeddings_col().find(
        {"chunk_id": {"$in": req.chunk_ids}},
        {
            "chunk_id": 1, "doc_id": 1, "page_number": 1, "chunk_type": 1,
            "chunk_text": 1, "section_title": 1, "format_provenance": 1,
            "gcs_image_path": 1, "chunk_index": 1,
        },
    ))
    if not chunks:
        raise HTTPException(status_code=404, detail="No chunks found for given chunk_ids")

    # Fetch parent documents
    doc_ids = list({c["doc_id"] for c in chunks})
    docs_map = {
        d["doc_id"]: d
        for d in get_documents_col().find(
            {"doc_id": {"$in": doc_ids}},
            {"doc_id": 1, "filename": 1, "original_format": 1},
        )
    }

    # Group by (doc_id, page_number), sort, merge adjacent
    by_doc: dict = defaultdict(list)
    for c in chunks:
        by_doc[c["doc_id"]].append(c)

    all_groups: list[dict] = []
    for doc_id, doc_chunks in by_doc.items():
        doc_chunks.sort(key=lambda x: (x["page_number"], x.get("chunk_index", 0)))
        for c in doc_chunks:
            all_groups.append({
                "doc_id": doc_id,
                "page_number": c["page_number"],
                "page_end": c["page_number"],
                "chunks": [c],
            })

    all_groups.sort(key=lambda x: (x["doc_id"], x["page_number"]))
    merged = _merge_adjacent(all_groups)

    citations = []
    for group in merged:
        doc_id = group["doc_id"]
        doc = docs_map.get(doc_id, {"doc_id": doc_id, "filename": "Unknown", "original_format": "pdf"})
        representative = group["chunks"][0]

        t_n = None
        if representative.get("chunk_type") == "table":
            t_n = _table_number(
                doc_id,
                representative["page_number"],
                representative.get("chunk_index", 0),
            )

        label = build_label(representative, doc, table_n=t_n)
        deep_link = build_deep_link(representative, doc_id)
        page_end = group["page_end"]

        citations.append({
            "label": label,
            "page_number": group["page_number"],
            "page_number_end": page_end if page_end != group["page_number"] else None,
            "doc_id": doc_id,
            "filename": doc.get("filename", ""),
            "chunk_type": representative.get("chunk_type", "text"),
            "deep_link": deep_link,
            "chunk_ids": [c["chunk_id"] for c in group["chunks"]],
        })

    _set_cached(key, req.chunk_ids, citations)
    logger.info(f"citations: built {len(citations)} citation(s) for {len(req.chunk_ids)} chunk_id(s)")
    return {"citations": citations, "count": len(citations), "cached": False}


@router.get("/citations/preview/{doc_id}/{page}")
async def citation_preview(doc_id: str, page: int):
    """
    Tooltip snippet: label + first 200 chars of the primary chunk on this page.
    Useful for hover previews in the UI.
    """
    doc = get_documents_col().find_one(
        {"doc_id": doc_id}, {"doc_id": 1, "filename": 1, "original_format": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    chunk = get_embeddings_col().find_one(
        {"doc_id": doc_id, "page_number": page},
        {
            "chunk_id": 1, "chunk_type": 1, "chunk_text": 1, "section_title": 1,
            "format_provenance": 1, "gcs_image_path": 1, "chunk_index": 1,
            "page_number": 1,
        },
        sort=[("chunk_index", 1)],
    )
    if not chunk:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks on page {page}. Page may be 'skip' type.",
        )

    t_n = None
    if chunk.get("chunk_type") == "table":
        t_n = _table_number(doc_id, page, chunk.get("chunk_index", 0))

    label = build_label(chunk, doc, table_n=t_n)
    snippet = (chunk.get("chunk_text") or "")[:200]

    return {
        "doc_id": doc_id,
        "page": page,
        "label": label,
        "snippet": snippet,
        "chunk_type": chunk.get("chunk_type"),
        "has_image": bool(chunk.get("gcs_image_path")),
        "deep_link": build_deep_link(chunk, doc_id),
    }


@router.get("/provenance/document/{doc_id}")
async def provenance_document(doc_id: str):
    """
    Full per-page provenance breakdown for a document.
    Every page that has chunks returns its label, snippet, and deep link.
    Includes skip pages (with 0 chunks) for completeness.
    """
    doc = get_documents_col().find_one({"doc_id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    for ts in ("created_at", "updated_at", "upload_timestamp"):
        if doc.get(ts):
            doc[ts] = doc[ts].isoformat()

    profiles = list(
        get_profiles_col()
        .find({"doc_id": doc_id}, {"_id": 0})
        .sort("page_number", 1)
    )

    pages = []
    for profile in profiles:
        page_num = profile["page_number"]
        if profile.get("created_at"):
            profile["created_at"] = profile["created_at"].isoformat()

        chunks = list(
            get_embeddings_col()
            .find(
                {"doc_id": doc_id, "page_number": page_num},
                {
                    "chunk_id": 1, "chunk_type": 1, "chunk_text": 1,
                    "section_title": 1, "format_provenance": 1,
                    "gcs_image_path": 1, "chunk_index": 1, "page_number": 1,
                },
            )
            .sort("chunk_index", 1)
        )

        chunk_summaries = []
        for c in chunks:
            t_n = None
            if c.get("chunk_type") == "table":
                t_n = _table_number(doc_id, page_num, c.get("chunk_index", 0))
            label = build_label(c, doc, table_n=t_n)
            chunk_summaries.append({
                "chunk_id": c["chunk_id"],
                "chunk_type": c["chunk_type"],
                "label": label,
                "snippet": (c.get("chunk_text") or "")[:120],
                "deep_link": build_deep_link(c, doc_id),
                "has_image": bool(c.get("gcs_image_path")),
            })

        pages.append({
            "page_number": page_num,
            "page_type": profile.get("page_type"),
            "chunk_count": len(chunks),
            "chunks": chunk_summaries,
        })

    return {
        "doc_id": doc_id,
        "filename": doc.get("filename"),
        "original_format": doc.get("original_format"),
        "total_pages": doc.get("total_pages"),
        "pages": pages,
        "document_metadata": doc,
    }


@router.get("/provenance/chunk/{chunk_id}")
async def provenance_chunk(chunk_id: str):
    """
    Full provenance trail for a single chunk: label, deep link, all metadata,
    parent document fields, and page_profile for the page it came from.
    """
    chunk = get_embeddings_col().find_one(
        {"chunk_id": chunk_id},
        {"_id": 0, "embedding": 0},  # exclude the 768-dim vector — all other fields included
    )
    if not chunk:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")

    doc = get_documents_col().find_one(
        {"doc_id": chunk["doc_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Parent document not found")

    profile = get_profiles_col().find_one(
        {"doc_id": chunk["doc_id"], "page_number": chunk["page_number"]},
        {"_id": 0},
    )

    # Serialise datetime fields
    for ts in ("created_at", "updated_at", "upload_timestamp"):
        if doc.get(ts):
            doc[ts] = doc[ts].isoformat()
    for ts in ("created_at", "updated_at"):
        if chunk.get(ts):
            chunk[ts] = chunk[ts].isoformat()
    if profile and profile.get("created_at"):
        profile["created_at"] = profile["created_at"].isoformat()

    t_n = None
    if chunk.get("chunk_type") == "table":
        t_n = _table_number(
            chunk["doc_id"], chunk["page_number"], chunk.get("chunk_index", 0)
        )

    label = build_label(chunk, doc, table_n=t_n)
    deep_link = build_deep_link(chunk, chunk["doc_id"])
    chunk_text = chunk.pop("chunk_text", "")

    return {
        "chunk_id": chunk_id,
        "citation": {
            "label": label,
            "deep_link": deep_link,
            "chunk_type": chunk.get("chunk_type"),
            "page_number": chunk.get("page_number"),
            "doc_id": chunk.get("doc_id"),
        },
        "chunk_text": chunk_text,
        "chunk_metadata": chunk,
        "page_profile": profile,
        "document": doc,
    }
