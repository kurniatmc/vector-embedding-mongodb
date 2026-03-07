"""
services/ingestion/app/processors/docx_processor.py
Handles DOCX by converting to PDF via Gotenberg, then delegating to PDFProcessor.
"""
import io
import os
import requests
from .base import BaseProcessor, NormalizedOutput
from .pdf_processor import PDFProcessor


def _convert_to_pdf(file_bytes: bytes, filename: str) -> bytes:
    libreoffice_url = os.getenv("LIBREOFFICE_URL", "http://libreoffice:3000")
    response = requests.post(
        f"{libreoffice_url}/forms/libreoffice/convert",
        files={"files": (filename, file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        timeout=120,
    )
    response.raise_for_status()
    return response.content


class DOCXProcessor(BaseProcessor):

    def validate(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        # DOCX is a ZIP — check magic bytes
        return file_bytes[:4] == b"PK\x03\x04"

    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        pdf_bytes = _convert_to_pdf(file_bytes, filename)
        pdf_proc = PDFProcessor()
        pdf_normalized = pdf_proc.normalize(pdf_bytes, filename.replace(".docx", ".pdf"))

        return NormalizedOutput(
            file_bytes=pdf_bytes,
            mime_type="application/pdf",
            page_count=pdf_normalized.page_count,
            metadata=pdf_normalized.metadata,
            provenance={
                "original_format": "docx",
                "converted_via": "gotenberg",
                "converted_page_count": pdf_normalized.page_count,
            },
        )

    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        return normalized.provenance
