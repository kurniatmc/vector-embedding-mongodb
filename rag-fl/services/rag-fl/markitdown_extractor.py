"""
services/rag-fl/markitdown_extractor.py
MarkItDown-based text extraction — comparison alternative to PyMuPDF.

Microsoft MarkItDown: https://github.com/microsoft/markitdown
pip install 'markitdown[all]'

Returns a list of section dicts so markitdown_pipeline.py can build ChunkRecords.
Keeps PyMuPDF pipeline 100% untouched.
"""
import io
import logging
import re

logger = logging.getLogger("ragfl.markitdown_extractor")

_MAX_SECTION_CHARS = 3000  # split sections larger than this at paragraph boundaries
_MIN_SECTION_CHARS = 50    # skip sections shorter than this (noise)


def _detect_actual_format(file_bytes: bytes, declared_format: str) -> str:
    """
    Detect the actual file format from magic bytes.
    Handles the case where GCS stores a Gotenberg-converted PDF under a DOCX/PPTX doc_id.
    """
    if file_bytes[:4] == b"%PDF":
        return "pdf"
    if file_bytes[:4] == b"PK\x03\x04":
        # ZIP-based Office format — trust the declared format
        return declared_format
    return declared_format


def extract_with_markitdown(
    file_bytes: bytes,
    filename: str,
    original_format: str,
) -> list[dict]:
    """
    Extract content using Microsoft MarkItDown library.

    Returns list of section dicts:
        {
            "page_number": int,   # 1-indexed (sheet index for Excel, section for others)
            "heading":     str,   # section heading or sheet name (may be empty)
            "content":     str,   # full section text, may contain markdown tables
            "is_table":    bool,  # True if content is primarily a markdown table
        }

    Empty / unreadable files → returns [].
    """
    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.error("markitdown not installed — run: pip install 'markitdown[all]'")
        return []

    md = MarkItDown()

    ext_map = {
        "pdf": ".pdf",  "xlsx": ".xlsx", "xls": ".xls",
        "docx": ".docx", "pptx": ".pptx",
        "yaml": ".yaml", "yml": ".yaml",
        "jpeg": ".jpg",  "jpg": ".jpg",  "png": ".png",
        "csv": ".csv",
    }

    # Detect actual format from magic bytes — GCS may store converted PDF for DOCX/PPTX
    actual_format = _detect_actual_format(file_bytes, original_format)
    if actual_format != original_format:
        logger.info(
            f"Format mismatch for {filename}: declared={original_format}, "
            f"detected={actual_format} — using detected format for MarkItDown"
        )
    ext = ext_map.get(actual_format, f".{actual_format}")

    try:
        result = md.convert(io.BytesIO(file_bytes), file_extension=ext)
        text = result.text_content or ""
    except Exception as exc:
        logger.warning(f"MarkItDown conversion failed for {filename} ({original_format}): {exc}")
        return []

    if not text.strip():
        logger.warning(f"MarkItDown produced empty content for {filename} ({original_format})")
        return []

    logger.info(f"MarkItDown extracted {len(text):,} chars from {filename}")

    # Dispatch on actual_format (not declared, in case bytes were converted)
    if actual_format in ("xlsx", "xls"):
        return _split_excel_sheets(text)
    elif actual_format in ("pdf", "pptx", "docx"):
        return _split_by_headings_or_pages(text, actual_format)
    elif actual_format in ("yaml", "yml"):
        return [{"page_number": 1, "heading": "", "content": text.strip(), "is_table": False}]
    elif actual_format in ("jpeg", "jpg", "png"):
        content = text.strip() or "[image — no text extracted by MarkItDown]"
        return [{"page_number": 1, "heading": "", "content": content, "is_table": False}]
    else:
        return _split_by_headings_or_pages(text, actual_format)


# ── Excel ─────────────────────────────────────────────────────────────────────

def _split_excel_sheets(text: str) -> list[dict]:
    """
    MarkItDown Excel output:  ## Sheet Name\\n|col|col|\\n|---|---|\\n|data|\\n\\n## Sheet2...
    Split on ## headings → one section per sheet.
    """
    parts = re.split(r"^(## .+)$", text, flags=re.MULTILINE)
    # parts[0]     = pre-heading content (usually empty)
    # parts[1::2]  = heading lines
    # parts[2::2]  = content after heading

    sections: list[dict] = []

    if len(parts) <= 1:
        if text.strip():
            sections.append({
                "page_number": 1,
                "heading": "Sheet1",
                "content": text.strip(),
                "is_table": _has_table(text),
            })
        return sections

    for i in range(1, len(parts), 2):
        heading_line = parts[i].strip()          # "## Sheet Name"
        heading = heading_line.lstrip("#").strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if not content:
            continue
        full = f"{heading_line}\n\n{content}"
        sections.append({
            "page_number": len(sections) + 1,
            "heading": heading,
            "content": full,
            "is_table": _has_table(content),
        })

    if not sections and text.strip():
        sections.append({
            "page_number": 1,
            "heading": "Sheet1",
            "content": text.strip(),
            "is_table": _has_table(text),
        })
    return sections


# ── PDF / DOCX / PPTX ─────────────────────────────────────────────────────────

def _split_by_headings_or_pages(text: str, fmt: str) -> list[dict]:
    if fmt == "pdf":
        pages = _try_split_by_page_markers(text)
        if pages:
            return pages
    sections = _split_by_headings(text)
    return sections if sections else _split_by_size(text)


def _try_split_by_page_markers(text: str) -> list[dict]:
    """Split on form-feed \\x0c (pdfminer page separator)."""
    if "\x0c" not in text:
        return []

    raw_pages = text.split("\x0c")
    sections: list[dict] = []
    for i, page_text in enumerate(raw_pages):
        content = page_text.strip()
        if len(content) < _MIN_SECTION_CHARS:
            continue
        if len(content) > _MAX_SECTION_CHARS:
            subs = _split_by_size(content, target_chars=_MAX_SECTION_CHARS)
            for j, s in enumerate(subs):
                s["page_number"] = len(sections) + 1
                s["heading"] = f"Page {i + 1}" + (f" (part {j + 1})" if j > 0 else "")
                sections.append(s)
        else:
            sections.append({
                "page_number": len(sections) + 1,
                "heading": f"Page {i + 1}",
                "content": content,
                "is_table": _has_table(content),
            })
    return sections


def _split_by_headings(text: str) -> list[dict]:
    """Split markdown text at # / ## / ### lines."""
    heading_re = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))
    if not matches:
        return []

    sections: list[dict] = []

    # Content before first heading
    pre = text[: matches[0].start()].strip()
    if len(pre) >= _MIN_SECTION_CHARS:
        sections.extend(_split_by_size(pre))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        heading_text = m.group(2).strip()

        if len(content) < _MIN_SECTION_CHARS:
            continue

        if len(content) > _MAX_SECTION_CHARS:
            subs = _split_by_size(content, target_chars=_MAX_SECTION_CHARS)
            for j, s in enumerate(subs):
                s["page_number"] = len(sections) + 1
                s["heading"] = heading_text + (f" (part {j + 1})" if j > 0 else "")
                sections.append(s)
        else:
            sections.append({
                "page_number": len(sections) + 1,
                "heading": heading_text,
                "content": content,
                "is_table": _has_table(content),
            })

    # Re-number sequentially
    for idx, s in enumerate(sections):
        s["page_number"] = idx + 1
    return sections


def _split_by_size(text: str, target_chars: int = 2000) -> list[dict]:
    """Split at paragraph boundaries into ≤ target_chars chunks."""
    if not text.strip():
        return []
    paragraphs = re.split(r"\n\n+", text.strip())
    sections: list[dict] = []
    buf: list[str] = []
    buf_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if buf_len + len(para) > target_chars and buf:
            content = "\n\n".join(buf)
            sections.append({
                "page_number": len(sections) + 1,
                "heading": "",
                "content": content,
                "is_table": _has_table(content),
            })
            buf, buf_len = [para], len(para)
        else:
            buf.append(para)
            buf_len += len(para)

    if buf:
        content = "\n\n".join(buf)
        sections.append({
            "page_number": len(sections) + 1,
            "heading": "",
            "content": content,
            "is_table": _has_table(content),
        })
    return sections


def _has_table(text: str) -> bool:
    """True if text contains at least 2 markdown table lines starting with |."""
    table_lines = [ln for ln in text.split("\n") if "|" in ln and ln.strip().startswith("|")]
    return len(table_lines) >= 2
