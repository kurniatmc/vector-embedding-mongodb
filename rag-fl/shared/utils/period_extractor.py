"""
shared/utils/period_extractor.py
Best-effort extraction of report period from filename, PDF metadata, and first-page text.
Used by both the ingestion service and the rag-fl pipeline.
"""
import re
import logging
from typing import Optional

logger = logging.getLogger("ragfl.period_extractor")

_MONTH_MAP = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09",
    "oct": "10", "nov": "11", "dec": "12",
}

_EMPTY_RESULT = {
    "report_period": None,
    "report_period_start": None,
    "report_period_end": None,
    "period_confidence": "none",
    "extraction_method": "none",
    "report_frequency": None,
    "report_series": None,
}


def extract_report_period(filename: str, file_bytes: bytes, mime_type: str) -> dict:
    """
    Best-effort extraction of report period metadata.
    Tries strategies in order: filename → PDF metadata → first-page text.
    Returns dict with chronological metadata fields.
    """
    result = dict(_EMPTY_RESULT)

    # Strategy 1: Filename patterns
    _try_filename(filename.lower(), result)
    if result["report_period"]:
        return result

    # Strategy 2: PDF metadata
    if "pdf" in mime_type:
        _try_pdf_metadata(file_bytes, result)
    if result["report_period"]:
        return result

    # Strategy 3: First-page text scan (PDF only)
    if "pdf" in mime_type:
        _try_first_page_text(file_bytes, result)

    return result


def _try_filename(filename_lower: str, result: dict) -> None:
    # Pattern: "January_2025", "Jan2025", "2025-January", "2025_Jan"
    for month_name, month_num in _MONTH_MAP.items():
        pattern = rf"{month_name}[_\-\s]?(\d{{4}})|(\d{{4}})[_\-\s]?{month_name}"
        m = re.search(pattern, filename_lower)
        if m:
            year = m.group(1) or m.group(2)
            result["report_period"] = f"{year}-{month_num}"
            result["period_confidence"] = "high"
            result["extraction_method"] = "filename"
            result["report_frequency"] = "monthly"
            return

    # Pattern: "YYYY-MM" or "YYYY_MM" (bare numeric)
    m = re.search(r"(\d{4})[_\-](\d{2})(?!\d)", filename_lower)
    if m:
        year, month = m.group(1), m.group(2)
        if 1 <= int(month) <= 12:
            result["report_period"] = f"{year}-{month}"
            result["period_confidence"] = "high"
            result["extraction_method"] = "filename"
            result["report_frequency"] = "monthly"
            return

    # Pattern: "Q1_2025", "2025-Q3", "2025Q4"
    m = re.search(r"q([1-4])[_\-]?(\d{4})|(\d{4})[_\-]?q([1-4])", filename_lower)
    if m:
        if m.group(1):
            quarter, year = m.group(1), m.group(2)
        else:
            year, quarter = m.group(3), m.group(4)
        result["report_period"] = f"{year}-Q{quarter}"
        result["period_confidence"] = "high"
        result["extraction_method"] = "filename"
        result["report_frequency"] = "quarterly"


def _try_pdf_metadata(file_bytes: bytes, result: dict) -> None:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        meta = doc.metadata or {}
        doc.close()
        creation = meta.get("creationDate", "") or meta.get("modDate", "") or ""
        # PDF date format: D:20250115120000+00'00'
        m = re.search(r"D:(\d{4})(\d{2})", creation)
        if m:
            result["report_period"] = f"{m.group(1)}-{m.group(2)}"
            result["period_confidence"] = "medium"
            result["extraction_method"] = "pdf_metadata"
            result["report_frequency"] = "monthly"
    except Exception as e:
        logger.debug(f"PDF metadata extraction failed: {e}")


def _try_first_page_text(file_bytes: bytes, result: dict) -> None:
    try:
        import fitz
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if doc.page_count == 0:
            doc.close()
            return
        first_text = doc[0].get_text()[:500].lower()
        doc.close()

        for month_name, month_num in _MONTH_MAP.items():
            pattern = rf"{month_name}[_\-\s]?(\d{{4}})|(\d{{4}})[_\-\s]?{month_name}"
            m = re.search(pattern, first_text)
            if m:
                year = m.group(1) or m.group(2)
                result["report_period"] = f"{year}-{month_num}"
                result["period_confidence"] = "medium"
                result["extraction_method"] = "first_page_text"
                result["report_frequency"] = "monthly"
                return
    except Exception as e:
        logger.debug(f"First-page text extraction failed: {e}")
