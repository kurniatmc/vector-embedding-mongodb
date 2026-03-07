"""
services/rag-fl/classifier.py
Phase 3A — Per-page classification: text | multimodal | table | mixed | skip
Zero API cost. Uses PyMuPDF (Layer 1), Pillow (Layer 2), pdfplumber (table override).
"""
import io
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image, ImageStat

logger = logging.getLogger("ragfl.classifier")

FORCE_MIXED_MODE = os.getenv("FORCE_MIXED_MODE", "false").lower() == "true"


@dataclass
class PageClassification:
    page_number: int        # 1-indexed
    page_type: str          # text | multimodal | table | mixed | skip | structured_text
    text_ratio: float
    image_ratio: float
    has_tables: bool
    detected_elements: list
    processing_recommendation: str
    estimated_text_tokens: int
    layer_used: str         # layer1 | layer2_pillow | table_override | forced_mixed | non_pdf


def classify_pdf_pages(file_bytes: bytes) -> list[PageClassification]:
    """Classify every page of a PDF. Prints console report. Returns list of PageClassification."""
    results = []

    if FORCE_MIXED_MODE:
        logger.info("FORCE_MIXED_MODE=true — skipping classification, all pages → mixed")
        fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
        count = fitz_doc.page_count
        fitz_doc.close()
        for i in range(count):
            results.append(PageClassification(
                page_number=i + 1, page_type="mixed",
                text_ratio=0.0, image_ratio=0.0, has_tables=False,
                detected_elements=["forced_mixed"],
                processing_recommendation="text_and_gemini_vision",
                estimated_text_tokens=0, layer_used="forced_mixed",
            ))
        return results

    fitz_doc = fitz.open(stream=file_bytes, filetype="pdf")
    with pdfplumber.open(io.BytesIO(file_bytes)) as plumber_doc:
        for idx in range(fitz_doc.page_count):
            page_num = idx + 1
            fitz_page = fitz_doc[idx]
            rect = fitz_page.rect
            page_area = rect.width * rect.height

            if page_area < 1.0:
                fitz_page = None
                results.append(_make_skip(page_num))
                continue

            # Layer 1 — PyMuPDF ratios
            blocks = fitz_page.get_text("blocks")
            text_area = sum(
                (b[2] - b[0]) * (b[3] - b[1]) for b in blocks if b[6] == 0
            )
            visual_area = sum(
                (b[2] - b[0]) * (b[3] - b[1]) for b in blocks if b[6] == 1
            )
            # Add vector drawings (charts, diagrams) at half weight
            for d in fitz_page.get_drawings():
                r = d.get("rect")
                if r and r.width > 0 and r.height > 0:
                    visual_area += r.width * r.height * 0.5

            visual_area = min(visual_area, page_area)
            text_ratio = min(text_area / page_area, 1.0)
            image_ratio = min(visual_area / page_area, 1.0)

            # Estimated tokens (rough: 1 token ≈ 4 chars)
            full_text = fitz_page.get_text()
            estimated_tokens = len(full_text) // 4

            # pdfplumber table detection
            has_tables = False
            try:
                pl_page = plumber_doc.pages[idx]
                tables = pl_page.extract_tables()
                has_tables = bool(tables)
            except Exception:
                has_tables = False

            # Layer 1 classification
            if text_ratio < 0.05 and image_ratio < 0.05:
                page_type, layer = "skip", "layer1"
            elif text_ratio > 0.70 and image_ratio < 0.20:
                page_type, layer = "text", "layer1"
            elif image_ratio > 0.50 and text_ratio < 0.20:
                page_type, layer = "multimodal", "layer1"
            elif text_ratio >= 0.20 or image_ratio >= 0.20:
                # Layer 2 — Pillow visual analysis for ambiguous pages
                page_type, layer = _layer2_pillow(fitz_page)
            else:
                page_type, layer = "mixed", "layer1_fallback"

            # XObject image check — handles PDFs where raster images are referenced
            # as XObjects via /Im0 Do (e.g. ChurnCustomer_Jan2025.pdf screenshot PDFs).
            # PyMuPDF get_text("blocks") only captures INLINE images (type 1 blocks);
            # XObject-referenced images are invisible to it and to get_drawings().
            # page.get_images() correctly enumerates all image XObjects on the page.
            # Only override when image_ratio is near 0 (i.e. images were missed by Layer 1).
            xobject_images = fitz_page.get_images()
            if xobject_images and image_ratio < 0.10:
                if text_ratio < 0.20:
                    page_type, layer = "multimodal", "xobject_image"
                    logger.info(
                        f"Page {page_num:3d} | xobject_image override → multimodal "
                        f"({len(xobject_images)} image XObject(s) found)"
                    )
                else:
                    page_type, layer = "mixed", "xobject_image"
                    logger.info(
                        f"Page {page_num:3d} | xobject_image override → mixed "
                        f"({len(xobject_images)} image XObject(s) found)"
                    )

            # Table override (after Layer 1/2 and XObject check, skip is immune)
            if has_tables and page_type != "skip":
                page_type, layer = "table", "table_override"

            detected = _detect_elements(page_type, has_tables, text_ratio, image_ratio, layer)
            rec = _processing_rec(page_type)

            # Console report (xobject_image override already logged inline above)
            if layer not in ("xobject_image",):
                if has_tables:
                    logger.info(
                        f"Page {page_num:3d} | {page_type:<13s} | pdfplumber: table(s) detected"
                    )
                else:
                    logger.info(
                        f"Page {page_num:3d} | {page_type:<13s} | "
                        f"text_ratio={text_ratio:.2f}, image_ratio={image_ratio:.2f}"
                    )

            results.append(PageClassification(
                page_number=page_num, page_type=page_type,
                text_ratio=round(text_ratio, 3), image_ratio=round(image_ratio, 3),
                has_tables=has_tables, detected_elements=detected,
                processing_recommendation=rec, estimated_text_tokens=estimated_tokens,
                layer_used=layer,
            ))
            # Free page object immediately
            fitz_page = None

    fitz_doc.close()
    return results


def _layer2_pillow(fitz_page) -> tuple[str, str]:
    """Render a small thumbnail and use Pillow color/edge analysis."""
    try:
        mat = fitz.Matrix(0.4, 0.4)  # low-res for analysis only
        pix = fitz_page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        del pix

        stat = ImageStat.Stat(img)
        color_variance = sum(stat.stddev[:3]) / 3.0
        gray_stddev = ImageStat.Stat(img.convert("L")).stddev[0]

        if color_variance > 40 or gray_stddev > 60:
            return "multimodal", "layer2_pillow"
        return "mixed", "layer2_pillow"
    except Exception:
        return "mixed", "layer2_fallback"


def _make_skip(page_num: int) -> PageClassification:
    return PageClassification(
        page_number=page_num, page_type="skip",
        text_ratio=0.0, image_ratio=0.0, has_tables=False,
        detected_elements=["blank"],
        processing_recommendation="skip",
        estimated_text_tokens=0, layer_used="layer1",
    )


def _detect_elements(page_type: str, has_tables: bool, tr: float, ir: float,
                     layer: str = "") -> list:
    elements = []
    if tr > 0.05:
        elements.append("text_blocks")
    if ir > 0.10:
        elements.append("images_or_drawings")
    if has_tables:
        elements.append("tables")
    if layer == "xobject_image":
        elements.append("xobject_images")
    elif page_type == "multimodal":
        elements.append("charts_or_diagrams")
    return elements or ["none"]


def _processing_rec(page_type: str) -> str:
    return {
        "text": "embed_text_only",
        "table": "pdfplumber_table_extract",
        "multimodal": "gemini_vision",
        "mixed": "text_and_gemini_vision",
        "skip": "skip",
        "structured_text": "embed_text_only",
    }.get(page_type, "embed_text_only")


def classify_non_pdf(original_format: str, page_count: int,
                     sheets_info: Optional[list] = None) -> list[PageClassification]:
    """Classify non-PDF logical pages (Excel sheets, YAML, JPEG/PNG)."""
    results = []
    for i in range(page_count):
        page_num = i + 1
        if original_format in ("xlsx", "xls"):
            sheet_name = (sheets_info[i]["name"] if sheets_info and i < len(sheets_info)
                          else f"Sheet{page_num}")
            logger.info(f"Page {page_num:3d} | table         | Excel sheet: {sheet_name}")
            results.append(PageClassification(
                page_number=page_num, page_type="table",
                text_ratio=0.0, image_ratio=0.0, has_tables=True,
                detected_elements=["table", f"sheet:{sheet_name}"],
                processing_recommendation="pdfplumber_table_extract",
                estimated_text_tokens=0, layer_used="non_pdf",
            ))
        elif original_format in ("yaml", "yml"):
            logger.info(f"Page {page_num:3d} | structured_text | YAML")
            results.append(PageClassification(
                page_number=page_num, page_type="structured_text",
                text_ratio=1.0, image_ratio=0.0, has_tables=False,
                detected_elements=["yaml_keys"],
                processing_recommendation="embed_text_only",
                estimated_text_tokens=0, layer_used="non_pdf",
            ))
        elif original_format in ("jpeg", "jpg", "png"):
            logger.info(f"Page {page_num:3d} | multimodal    | Image file")
            results.append(PageClassification(
                page_number=page_num, page_type="multimodal",
                text_ratio=0.0, image_ratio=1.0, has_tables=False,
                detected_elements=["image"],
                processing_recommendation="gemini_vision",
                estimated_text_tokens=0, layer_used="non_pdf",
            ))
    return results
