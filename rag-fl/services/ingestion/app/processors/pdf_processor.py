"""
services/ingestion/app/processors/pdf_processor.py
Handles PDF files. Uses PyMuPDF for page count + structure metadata.
"""
import fitz  # PyMuPDF
from .base import BaseProcessor, NormalizedOutput


class PDFProcessor(BaseProcessor):

    def validate(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            valid = doc.page_count > 0
            doc.close()
            return valid
        except Exception:
            return False

    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        page_count = doc.page_count
        metadata = doc.metadata or {}
        doc.close()
        return NormalizedOutput(
            file_bytes=file_bytes,
            mime_type="application/pdf",
            page_count=page_count,
            metadata={
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "subject": metadata.get("subject", ""),
            },
            provenance={"original_format": "pdf", "page_count": page_count},
        )

    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        return normalized.provenance
