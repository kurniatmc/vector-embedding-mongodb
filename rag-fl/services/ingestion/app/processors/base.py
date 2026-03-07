"""
services/ingestion/app/processors/base.py
Abstract base class for all format processors.
Adding a new format = subclass BaseProcessor + register in REGISTRY. Nothing else.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class NormalizedOutput:
    file_bytes: bytes          # canonical bytes (PDF for converted formats)
    mime_type: str             # canonical MIME type post-normalization
    page_count: int            # logical pages (PDF pages, Excel sheets, etc.)
    metadata: dict             # general metadata (title, author, etc.)
    provenance: dict           # format-specific provenance fields


class BaseProcessor(ABC):

    @abstractmethod
    def validate(self, file_bytes: bytes) -> bool:
        """Return True if the file is non-empty and structurally valid."""

    @abstractmethod
    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        """
        Normalize to canonical form and extract all provenance.
        PPTX/DOCX: convert to PDF via LibreOffice, then process as PDF.
        Must populate page_count and provenance before returning.
        """

    @abstractmethod
    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        """
        Return format_provenance dict for the documents MongoDB record.
        PDF:   {"original_format": "pdf", "page_count": int}
        Excel: {"original_format": "xlsx", "sheets": [{"name": str, "row_count": int}]}
        YAML:  {"original_format": "yaml", "top_level_keys": list[str]}
        Image: {"original_format": "jpeg|png", "width": int, "height": int}
        PPTX:  {"original_format": "pptx", "slide_count": int, "converted_via": "gotenberg"}
        DOCX:  {"original_format": "docx", "page_count": int, "converted_via": "gotenberg"}
        """
