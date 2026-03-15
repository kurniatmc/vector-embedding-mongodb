"""
shared/utils/vector_search.py

Single entry-point for vector search.  Auto-switches based on VECTOR_SEARCH_BACKEND:
  - local  → Python cosine similarity (MongoDB Community, no $vectorSearch)
  - atlas  → Atlas $vectorSearch pipeline (Local Atlas or Atlas Cloud)

Rule from ARCHITECTURE.md:
  Always call vector_search() — never write raw MongoDB queries for embeddings.
  Zero code changes needed when migrating between local and Atlas; only .env changes.

Environment Variables:
  VECTOR_SEARCH_BACKEND=local|atlas (default: local)
  MONGODB_URI=connection string
"""
import os

import numpy as np
from pymongo.collection import Collection


def cosine_similarity(a: list, b: list) -> float:
    va, vb = np.array(a, dtype=np.float32), np.array(b, dtype=np.float32)
    norm = np.linalg.norm(va) * np.linalg.norm(vb)
    if norm == 0:
        return 0.0
    return float(np.dot(va, vb) / norm)


def vector_search(
    collection: Collection,
    query_vector: list[float],
    top_k: int = 5,
    filter_query: dict | None = None,
) -> list[dict]:
    """Search for the top-k most similar chunks.

    Args:
        collection:   doc_embeddings MongoDB collection.
        query_vector: 768-dim embedding from text-embedding-004
                      with task_type="RETRIEVAL_QUERY".
        top_k:        Number of results to return.
        filter_query: Optional MongoDB filter (e.g. {"doc_id": "abc"}).

    Returns:
        List of chunk dicts, sorted by "score" descending.
    """
    backend = os.getenv("VECTOR_SEARCH_BACKEND", "local").lower()
    if backend == "atlas":
        return _atlas_search(collection, query_vector, top_k, filter_query)
    return _local_search(collection, query_vector, top_k, filter_query)


# ── Atlas $vectorSearch (production) ─────────────────────────────────────────

def _atlas_search(
    collection: Collection,
    query_vector: list[float],
    top_k: int,
    filter_query: dict | None,
) -> list[dict]:
    """Uses MongoDB Atlas $vectorSearch.

    Requires an Atlas Search index named "embedding_index" on the "embedding"
    field with numDimensions=768 and similarity=cosine.
    Create via Atlas UI: Search > Create Index > Vector > embedding_index.
    """
    vector_stage: dict = {
        "index": "embedding_index",
        "path": "embedding",
        "queryVector": query_vector,
        "numCandidates": top_k * 10,
        "limit": top_k,
    }
    if filter_query:
        vector_stage["filter"] = filter_query

    pipeline = [
        {"$vectorSearch": vector_stage},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
    ]
    return list(collection.aggregate(pipeline))


# ── Local cosine similarity (development) ────────────────────────────────────

# Fields fetched from MongoDB — embedding for scoring, rest for citation engine
_LOCAL_PROJECTION = {
    "embedding": 1,
    "chunk_id": 1,
    "chunk_text": 1,
    "chunk_type": 1,
    "page_number": 1,
    "doc_id": 1,
    "gcs_image_path": 1,
    "section_title": 1,
    "format_provenance": 1,
    "bounding_box": 1,
}


def _local_search(
    collection: Collection,
    query_vector: list[float],
    top_k: int,
    filter_query: dict | None,
) -> list[dict]:
    """In-memory cosine similarity over all stored embeddings.

    Fetches only required projection fields to minimise memory usage.
    Suitable for development with < ~50k chunks.
    """
    candidates = list(collection.find(filter_query or {}, _LOCAL_PROJECTION))

    scored = []
    for doc in candidates:
        emb = doc.get("embedding")
        if emb:
            doc["score"] = cosine_similarity(query_vector, emb)
            scored.append(doc)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
