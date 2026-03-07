"""
services/rag-fl/embedder.py
Batch embedding via Google gemini-embedding-001, output_dimensionality=768.
Always task_type="RETRIEVAL_DOCUMENT" for stored chunks — NEVER mix with RETRIEVAL_QUERY.
See ARCHITECTURE.md: "Asymmetric Task Types — MANDATORY, NEVER MIX"

Note: text-embedding-004 is not available with this API key.
gemini-embedding-001 with output_dimensionality=768 is used instead for full schema
compatibility with the 768-dim MongoDB vector index.
"""
import logging
import os

from google import genai
from google.genai import types

logger = logging.getLogger("ragfl.embedder")

# gemini-embedding-001 supports output_dimensionality=768 (matching MongoDB index)
_MODEL = "models/gemini-embedding-001"
_DIMS = 768
_BATCH_SIZE = 100  # group for logging only; API called per-item


def _get_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return genai.Client(api_key=api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of texts. Returns list of 768-dim float vectors in input order.
    task_type is always RETRIEVAL_DOCUMENT.
    """
    if not texts:
        return []

    client = _get_client()
    all_embeddings: list[list[float]] = []
    total_batches = (len(texts) + _BATCH_SIZE - 1) // _BATCH_SIZE

    for batch_idx, i in enumerate(range(0, len(texts), _BATCH_SIZE)):
        batch = texts[i: i + _BATCH_SIZE]
        logger.info(f"Embedding batch {batch_idx + 1}/{total_batches}: {len(batch)} chunks")

        for text in batch:
            result = client.models.embed_content(
                model=_MODEL,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=_DIMS,
                ),
            )
            all_embeddings.append(result.embeddings[0].values)

    return all_embeddings


def embed_single(text: str) -> list[float]:
    """Embed a single text string."""
    return embed_texts([text])[0]
