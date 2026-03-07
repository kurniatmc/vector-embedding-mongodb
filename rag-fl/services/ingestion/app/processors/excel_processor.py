"""
services/ingestion/app/processors/excel_processor.py
Handles .xlsx and .xls files. Each sheet = one logical "page".
"""
import io
import openpyxl
from .base import BaseProcessor, NormalizedOutput


class ExcelProcessor(BaseProcessor):

    def validate(self, file_bytes: bytes) -> bool:
        if not file_bytes:
            return False
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            valid = len(wb.sheetnames) > 0
            wb.close()
            return valid
        except Exception:
            return False

    def normalize(self, file_bytes: bytes, filename: str) -> NormalizedOutput:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        sheets = []
        for name in wb.sheetnames:
            ws = wb[name]
            row_count = ws.max_row or 0
            sheets.append({"name": name, "row_count": row_count})
        wb.close()

        return NormalizedOutput(
            file_bytes=file_bytes,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            page_count=len(sheets),
            metadata={"sheet_names": [s["name"] for s in sheets]},
            provenance={"original_format": "xlsx", "sheets": sheets},
        )

    def extract_provenance(self, normalized: NormalizedOutput) -> dict:
        return normalized.provenance
