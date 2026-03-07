"""
shared/schemas/chunk.py
Canonical Chunk Schema — every doc_embeddings document must have ALL these fields.
Defined in ARCHITECTURE.md.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class ChunkRecord(BaseModel):
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str

    # Provenance — drives citation requirement
    page_number: int              # 1-indexed. Excel=sheet index. YAML=1.
    bounding_box: Optional[BoundingBox] = None  # None for non-visual
    section_title: str = ""
    chunk_index: int = 0          # position within page, 0-indexed

    format_provenance: dict = Field(default_factory=dict)
    # PDF:   {"original_format": "pdf"}
    # Excel: {"original_format": "xlsx", "sheet_name": str, "row_start": int, "row_end": int}
    # YAML:  {"original_format": "yaml", "key_path": str}
    # Image: {"original_format": "jpeg/png", "original_filename": str}
    # PPTX:  {"original_format": "pptx", "slide_number": int}

    chunk_type: str               # "text" | "table" | "multimodal"
    chunk_text: str               # text OR Gemini Vision description
    gcs_image_path: Optional[str] = None  # GCS path for multimodal, None otherwise

    embedding: Optional[list[float]] = None  # 768 dims, text-embedding-004
    embedding_model: Optional[str] = None    # "models/text-embedding-004"
    embedding_task_type: str = "RETRIEVAL_DOCUMENT"  # always RETRIEVAL_DOCUMENT for stored chunks

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_mongo(self) -> dict:
        d = self.model_dump()
        if d.get("bounding_box") is not None:
            d["bounding_box"] = d["bounding_box"]
        return d
