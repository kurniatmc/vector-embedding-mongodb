"""
services/ingestion/app/processors/yaml_processor.py
Handles .yaml / .yml files. Logical page count = 1.
"""
import yaml
from .base import BaseProcessor, NormalizedOutput


class YAMLProcessor(BaseProcessor):

    def validate(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        try:
            data = yaml.safe_load(file_bytes.decode("utf-8", errors="replace"))
            return data is not None
        except Exception:
            return False

    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        text = file_bytes.decode("utf-8", errors="replace")
        data = yaml.safe_load(text) or {}
        top_level_keys = list(data.keys()) if isinstance(data, dict) else []

        return NormalizedOutput(
            file_bytes=file_bytes,
            mime_type="application/x-yaml",
            page_count=1,
            metadata={"top_level_keys": top_level_keys},
            provenance={"original_format": "yaml", "top_level_keys": top_level_keys},
        )

    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        return normalized.provenance
