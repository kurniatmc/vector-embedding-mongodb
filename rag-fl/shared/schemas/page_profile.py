"""
shared/schemas/page_profile.py
Pydantic model for the MongoDB `page_profiles` collection.
Populated by Phase 4 (Per-Page Analysis).
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class PageProfile(BaseModel):
    doc_id: str
    page_number: int              # 1-indexed
    page_type: str                # "text" | "multimodal" | "table" | "mixed" | "skip" | "structured_text"
    detected_elements: list = Field(default_factory=list)  # list of {type, bbox, ...} dicts or legacy strings
    processing_recommendation: str = ""  # e.g. "embed_text_only" | "gemini_vision" | "skip"
    estimated_text_tokens: int = 0
    has_tables: bool = False
    text_ratio: Optional[float] = None   # from PyMuPDF Layer 1
    image_ratio: Optional[float] = None  # from PyMuPDF Layer 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_mongo(self) -> dict:
        return self.model_dump()
