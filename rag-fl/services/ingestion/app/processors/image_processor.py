"""
services/ingestion/app/processors/image_processor.py
Handles JPEG and PNG. Single logical "page". Dimensions from Pillow.
"""
import io
from PIL import Image
from .base import BaseProcessor, NormalizedOutput


class ImageProcessor(BaseProcessor):

    def validate(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
            return True
        except Exception:
            return False

    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        img = Image.open(io.BytesIO(file_bytes))
        width, height = img.size
        fmt = (img.format or "").lower()
        original_format = "jpeg" if fmt in ("jpg", "jpeg") else fmt

        return NormalizedOutput(
            file_bytes=file_bytes,
            mime_type=f"image/{original_format}",
            page_count=1,
            metadata={"width": width, "height": height, "mode": img.mode},
            provenance={
                "original_format": original_format,
                "original_filename": filename,
                "width": width,
                "height": height,
            },
        )

    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        return normalized.provenance
