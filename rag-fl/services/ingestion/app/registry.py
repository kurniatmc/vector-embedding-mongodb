"""
services/ingestion/app/registry.py
Format Registry: MIME type → Processor class.
Adding a new format = add one entry to REGISTRY. Nothing else changes.
"""
import magic
from .processors.base import BaseProcessor
from .processors.pdf_processor import PDFProcessor
from .processors.excel_processor import ExcelProcessor
from .processors.pptx_processor import PPTXProcessor
from .processors.docx_processor import DOCXProcessor
from .processors.yaml_processor import YAMLProcessor
from .processors.image_processor import ImageProcessor


REGISTRY: dict[str, type[BaseProcessor]] = {
    "application/pdf":                                                              PDFProcessor,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":           ExcelProcessor,
    "application/vnd.ms-excel":                                                     ExcelProcessor,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":   PPTXProcessor,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document":     DOCXProcessor,
    "application/x-yaml":   YAMLProcessor,
    "text/yaml":            YAMLProcessor,
    "text/x-yaml":          YAMLProcessor,
    "text/plain":           YAMLProcessor,  # fallback for .yaml files misdetected as text/plain
    "image/jpeg":           ImageProcessor,
    "image/png":            ImageProcessor,
    "image/bmp":            ImageProcessor,
    "image/tiff":           ImageProcessor,
    "image/gif":            ImageProcessor,
    "image/webp":           ImageProcessor,
}

# Extension fallback for when MIME detection is ambiguous
EXTENSION_FALLBACK: dict[str, str] = {
    ".pdf":   "application/pdf",
    ".xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":   "application/vnd.ms-excel",
    ".pptx":  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".yaml":  "application/x-yaml",
    ".yml":   "application/x-yaml",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".png":   "image/png",
    ".bmp":   "image/bmp",
    ".tiff":  "image/tiff",
    ".tif":   "image/tiff",
    ".gif":   "image/gif",
    ".webp":  "image/webp",
}


class UnsupportedFormatError(Exception):
    pass


def detect_mime_type(file_bytes: bytes, filename: str) -> str:
    """Detect MIME type using libmagic, with extension fallback."""
    try:
        detected = magic.from_buffer(file_bytes[:4096], mime=True)
    except Exception:
        detected = "application/octet-stream"

    # If libmagic returns a generic type, use the extension
    if detected in ("application/octet-stream", "application/zip", "text/plain"):
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in EXTENSION_FALLBACK:
            return EXTENSION_FALLBACK[ext]

    return detected


def get_processor(file_bytes: bytes, filename: str) -> tuple[BaseProcessor, str]:
    """
    Returns (processor_instance, detected_mime_type).
    Raises UnsupportedFormatError for unknown formats.
    """
    mime_type = detect_mime_type(file_bytes, filename)
    processor_class = REGISTRY.get(mime_type)
    if not processor_class:
        raise UnsupportedFormatError(
            f"No processor registered for MIME type '{mime_type}' (file: {filename})"
        )
    return processor_class(), mime_type
