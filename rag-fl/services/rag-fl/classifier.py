"""
services/rag-fl/classifier.py
Phase 3A — Sub-page element detection.

Instead of one label per page, detects ALL elements present:
  • tables  (pdfplumber, loose settings — catches small tables)
  • visuals (PyMuPDF get_images + get_drawings, clustered by proximity)
  • text    (PyMuPDF blocks, after filtering table/visual overlaps)

page_type is derived from what was actually found:
  any visual + anything else → "mixed"
  visual only               → "multimodal"
  table + text              → "mixed"
  table only                → "table"
  text only                 → "text"
  nothing                   → "skip"

detected_elements is a list of typed dicts:
  [{"type": "table",  "bbox": [...], "table_index": 0},
   {"type": "visual", "bbox": [...]},
   {"type": "text",   "bbox": [...], "char_count": 340}]

These dicts drive per-element chunking in pipeline.py.
FORCE_MIXED_MODE bypasses all detection and marks pages "mixed".
"""
import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

import fitz  # PyMuPDF
import pdfplumber
from PIL import Image, ImageStat

logger = logging.getLogger("ragfl.classifier")

FORCE_MIXED_MODE = os.getenv("FORCE_MIXED_MODE", "false").lower() == "true"

# ── Detection thresholds ──────────────────────────────────────────────────────
_MIN_VISUAL_AREA_RATIO = 0.03    # visual cluster must cover > 3% of page area
_MIN_IMAGE_AREA_RATIO  = 0.005   # individual image XObject must exceed 0.5% of page area
_MIN_DRAW_AREA_RATIO   = 0.005   # individual drawing must exceed 0.5% to join cluster
_MIN_TEXT_CHARS        = 100     # page must have ≥ 100 non-table/visual chars → "has text"
_MIN_BLOCK_CHARS       = 20      # individual text block must have ≥ 20 chars
_CLUSTER_GAP           = 20      # points — drawings within this gap are merged
_TABLE_OVERLAP_THRESH  = 0.5     # text block > 50% inside table bbox → excluded
_VISUAL_OVERLAP_THRESH = 0.3     # text block >= 30% inside visual bbox → excluded (label/caption)
_VISUAL_TABLE_THRESH   = 0.7     # visual cluster > 70% inside table bbox → discarded

# pdfplumber table detection settings — looser than default to catch small tables
_TABLE_SETTINGS = {
    "vertical_strategy":   "lines",
    "horizontal_strategy": "lines",
    "min_words_vertical":  1,
    "min_words_horizontal": 1,
    "snap_tolerance":      3,
    "join_tolerance":      3,
    "edge_min_length":     3,
}

# Strategy 2: text-based column alignment + line-based rows.
# Catches tables with only horizontal separators (no vertical borders).
_TABLE_SETTINGS_TEXT_LINES = {
    "vertical_strategy":    "text",
    "horizontal_strategy":  "lines",
    "min_words_vertical":   2,
    "min_words_horizontal": 1,
    "snap_tolerance":       5,
    "join_tolerance":       5,
    "edge_min_length":      10,
    "text_x_tolerance":     5,
    "text_y_tolerance":     5,
}

# Minimum non-empty cells to accept a pdfplumber table (Issue 5: phantom tables)
_MIN_TABLE_CELLS = 4

# Maximum AVERAGE cell length to accept as structured table (not prose).
# Uses average (not max/all) so that a single long description cell in an
# otherwise short-celled table is not falsely rejected.
# Prose paragraphs detected as tables have avg ~85+ chars; real data tables ~5-20 chars.
_MAX_PROSE_CELL_LEN = 60


# ── PageClassification dataclass (unchanged shape — detected_elements now list[dict]) ─

@dataclass
class PageClassification:
    page_number: int
    page_type: str          # text | multimodal | table | mixed | skip | structured_text
    text_ratio: float
    image_ratio: float
    has_tables: bool
    detected_elements: list  # list of {type, bbox, ...} dicts; ["blank"] for skip
    processing_recommendation: str
    estimated_text_tokens: int
    layer_used: str


# ── Main entry point ──────────────────────────────────────────────────────────

def classify_pdf_pages(file_bytes: bytes) -> list[PageClassification]:
    """
    Run sub-page element detection on every page of a PDF.
    Returns one PageClassification per page with detected_elements as typed dicts.
    """
    results = []

    if FORCE_MIXED_MODE:
        logger.info("FORCE_MIXED_MODE=true — skipping element detection, all pages → mixed")
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
                results.append(_make_skip(page_num))
                fitz_page = None
                continue

            # Pre-fetch text blocks once (used for text_ratio + element detection)
            raw_blocks = fitz_page.get_text("blocks")
            full_text = "\n".join(b[4] for b in raw_blocks if b[6] == 0)
            estimated_tokens = len(full_text) // 4
            text_area = sum(
                (b[2] - b[0]) * (b[3] - b[1]) for b in raw_blocks if b[6] == 0
            )
            text_ratio = min(text_area / page_area, 1.0)

            # ── Step 1: Table detection ──────────────────────────────────────
            # Two rect lists:
            #   lines_table_rects  — pdfplumber LINES strategy (reliable; can discard visuals)
            #   soft_table_rects   — whitespace / text+lines (heuristic; used only for
            #                        text-block exclusion, NOT for discarding visuals)
            tables_data: list[dict] = []
            lines_table_rects: list[fitz.Rect] = []   # reliable tables only
            soft_table_rects: list[fitz.Rect] = []    # heuristic tables
            try:
                pl_page = plumber_doc.pages[idx]
                plumber_tables = pl_page.find_tables(table_settings=_TABLE_SETTINGS)
                for t_idx, t in enumerate(plumber_tables):
                    data = t.extract()
                    if not data:
                        continue
                    non_empty = sum(1 for row in data for cell in row
                                    if cell and str(cell).strip())
                    if non_empty < _MIN_TABLE_CELLS:
                        continue
                    num_rows = len(data)
                    num_cols = max(len(row) for row in data)
                    if num_rows <= 1 and num_cols <= 1:
                        continue
                    nonempty_cells = [str(c).strip() for row in data
                                      for c in row if c and str(c).strip()]
                    if nonempty_cells:
                        avg_cell_len = sum(len(c) for c in nonempty_cells) / len(nonempty_cells)
                        if avg_cell_len > _MAX_PROSE_CELL_LEN:
                            continue
                    try:
                        tr = fitz.Rect(t.bbox)
                    except Exception:
                        continue
                    tables_data.append({
                        "type": "table",
                        "bbox": list(t.bbox),
                        "table_index": t_idx,
                    })
                    lines_table_rects.append(tr)
            except Exception as e:
                logger.debug(f"Page {page_num}: pdfplumber table detection: {e}")

            # Combined rect list for text-block filtering (all detected tables)
            table_fitz_rects = lines_table_rects + soft_table_rects

            # ── Step 1B: Whitespace-aligned table detection ──────────────────
            # Detects tables with no borders/lines — words aligned into columns.
            # Results go into soft_table_rects (NOT lines_table_rects) so they
            # cannot accidentally discard genuine visual elements.
            try:
                ws_tables = _detect_whitespace_tables(pl_page.extract_words(x_tolerance=3))
                for ws_tbl in ws_tables:
                    ws_rect = fitz.Rect(ws_tbl["bbox"])
                    # Skip if substantially overlaps an already-detected pdfplumber table,
                    # OR if it wraps around an existing table (bidirectional check).
                    # A large false-positive table that contains real tables has a low
                    # forward overlap ratio but a high reverse ratio (existing ⊂ candidate).
                    if any(_overlap_ratio(ws_rect, tr) > 0.5 or _overlap_ratio(tr, ws_rect) > 0.5
                           for tr in lines_table_rects):
                        continue
                    t_idx = len(tables_data)
                    tables_data.append({
                        "type": "table",
                        "bbox": ws_tbl["bbox"],
                        "table_index": t_idx,
                        "is_whitespace_table": True,
                        "rows": ws_tbl["rows"],
                    })
                    soft_table_rects.append(ws_rect)
                    table_fitz_rects = lines_table_rects + soft_table_rects
            except Exception as e:
                logger.debug(f"Page {page_num}: whitespace table detection: {e}")

            # ── Step 2: Image / chart detection ─────────────────────────────

            # Step 2A: Images — each XObject is a SEPARATE visual element (no clustering)
            # Preserves individual image boundaries even for tightly-packed layouts
            image_rects: list[fitz.Rect] = []
            for img_info in fitz_page.get_images(full=True):
                try:
                    bbox = fitz_page.get_image_bbox(img_info)
                    if bbox and not bbox.is_empty and bbox.get_area() > page_area * _MIN_IMAGE_AREA_RATIO:
                        image_rects.append(fitz.Rect(bbox))
                        logger.debug(f"Page {page_num}: Image XObject bbox={bbox}")
                except Exception:
                    pass

            visual_elements: list[dict] = []
            for img_rect in image_rects:
                # Discard if almost entirely inside a reliable (lines-strategy) table
                if any(_overlap_ratio(img_rect, tr) > _VISUAL_TABLE_THRESH
                       for tr in lines_table_rects):
                    continue
                if img_rect.get_area() < page_area * _MIN_VISUAL_AREA_RATIO:
                    continue
                # Skip if the image bbox has substantial readable text underneath it.
                # This handles PDFs where a decorative border/box is stored as an image
                # XObject but the actual text content sits on a separate text layer.
                # For such cases we want the text layer (Step 3) to handle the content,
                # not Gemini Vision.  Genuine chart/photo XObjects have little or no
                # underlying text (axis labels only, well below the threshold).
                try:
                    text_under = fitz_page.get_text("text", clip=img_rect).strip()
                    if len(text_under) >= _MIN_TEXT_CHARS:
                        logger.debug(
                            f"Page {page_num}: Image XObject at {img_rect} skipped "
                            f"(text layer has {len(text_under)} chars — treated as text region)"
                        )
                        continue
                except Exception:
                    pass
                visual_elements.append({
                    "type": "visual",
                    "bbox": [img_rect.x0, img_rect.y0, img_rect.x1, img_rect.y1],
                })

            # Step 2B: Drawings — gap-cluster (same as before) to form chart regions,
            # but skip clusters already covered by an image XObject.
            # This preserves chart detection while avoiding double-detection with images.
            drawing_rects: list[fitz.Rect] = []
            for d in fitz_page.get_drawings():
                r = d.get("rect")
                if not r:
                    continue
                try:
                    fr = fitz.Rect(r)
                    if not fr.is_empty and fr.get_area() > page_area * _MIN_DRAW_AREA_RATIO:
                        drawing_rects.append(fr)
                except Exception:
                    pass

            if drawing_rects:
                drawing_clusters = _cluster_rects(drawing_rects, gap=_CLUSTER_GAP)
                for cluster in drawing_clusters:
                    if cluster.get_area() < page_area * _MIN_VISUAL_AREA_RATIO:
                        continue
                    # Discard if almost entirely inside a reliable table
                    if any(_overlap_ratio(cluster, tr) > _VISUAL_TABLE_THRESH
                           for tr in lines_table_rects):
                        continue
                    # Skip if already substantially covered by a detected image XObject
                    cluster_area = cluster.get_area()
                    if cluster_area > 0 and any(
                        (cluster & img_rect).get_area() / cluster_area > 0.7
                        for img_rect in image_rects
                    ):
                        continue
                    visual_elements.append({
                        "type": "visual",
                        "bbox": [cluster.x0, cluster.y0, cluster.x1, cluster.y1],
                    })

            visual_fitz_rects = [fitz.Rect(v["bbox"]) for v in visual_elements]

            # ── Step 1C: Horizontal-line-only tables (text+lines strategy) ───
            # Runs AFTER visual detection so its table bboxes cannot suppress visuals.
            # Results go into soft_table_rects only.
            try:
                tl_tables = pl_page.find_tables(table_settings=_TABLE_SETTINGS_TEXT_LINES)
                for t in tl_tables:
                    try:
                        tr_new = fitz.Rect(t.bbox)
                    except Exception:
                        continue
                    # Skip if substantially covered by already-detected table,
                    # OR if it wraps around an existing table (bidirectional check).
                    # A large false-positive table that contains real tables has a low
                    # forward overlap ratio but a high reverse ratio (existing ⊂ candidate).
                    all_existing = lines_table_rects + soft_table_rects
                    if any(_overlap_ratio(tr_new, ex) > 0.5 or _overlap_ratio(ex, tr_new) > 0.5
                           for ex in all_existing):
                        continue
                    # Skip if it substantially overlaps a detected visual element
                    if any(_overlap_ratio(tr_new, vr) > 0.4 for vr in visual_fitz_rects):
                        continue
                    data = t.extract()
                    if not data:
                        continue
                    non_empty = sum(1 for row in data for cell in row
                                    if cell and str(cell).strip())
                    if non_empty < _MIN_TABLE_CELLS:
                        continue
                    num_rows = len(data)
                    num_cols = max(len(row) for row in data)
                    if num_rows <= 1 and num_cols <= 1:
                        continue
                    nonempty_cells = [str(c).strip() for row in data
                                      for c in row if c and str(c).strip()]
                    if nonempty_cells:
                        avg_cell_len = sum(len(c) for c in nonempty_cells) / len(nonempty_cells)
                        if avg_cell_len > _MAX_PROSE_CELL_LEN:
                            continue
                    t_idx = len(tables_data)
                    tables_data.append({
                        "type": "table",
                        "bbox": list(t.bbox),
                        "table_index": t_idx,
                        "rows": data,
                    })
                    soft_table_rects.append(tr_new)
                    table_fitz_rects = lines_table_rects + soft_table_rects
            except Exception as e:
                logger.debug(f"Page {page_num}: text+lines table detection: {e}")

            # ── Step 2B: Pixel fallback — catch visual content missed by vector methods ──
            # Renders a low-res thumbnail and checks for significant non-white pixel content
            # in areas not already covered by detected tables or visuals.
            # Catches: pivot tables as images, embedded screenshots, Form XObjects with
            # drawing elements too small to exceed _MIN_DRAW_AREA_RATIO individually.
            try:
                all_detected_rects = table_fitz_rects + visual_fitz_rects
                covered_area = sum(r.get_area() for r in all_detected_rects)
                # Only run pixel scan if page seems under-detected relative to its area
                if covered_area / max(page_area, 1) < 0.5:
                    thumb = fitz_page.get_pixmap(
                        matrix=fitz.Matrix(0.25, 0.25), colorspace=fitz.csGRAY
                    )
                    non_white = sum(b < 240 for b in thumb.samples)
                    total_px = thumb.width * thumb.height
                    del thumb
                    non_white_ratio = non_white / total_px if total_px > 0 else 0
                    # Trigger: significant non-white content AND more than detected area suggests
                    # AND not a text-heavy page (text chars are detected separately)
                    if (non_white_ratio > 0.20
                            and non_white_ratio > covered_area / max(page_area, 1) + 0.10
                            and text_ratio < 0.5):
                        visual_elements.append({
                            "type": "visual",
                            "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                            "pixel_detected": True,
                        })
                        visual_fitz_rects.append(fitz.Rect(rect))
                        logger.info(
                            f"Page {page_num}: pixel fallback visual "
                            f"(non_white={non_white_ratio:.2%}, covered={covered_area/page_area:.2%})"
                        )
            except Exception as e:
                logger.debug(f"Page {page_num}: pixel fallback: {e}")

            # ── Step 3: Text block detection (filtered) ───────────────────────
            text_elements: list[dict] = []
            text_char_count = 0
            for block in raw_blocks:
                if block[6] != 0:
                    continue
                block_text = block[4].strip()
                if len(block_text) < _MIN_BLOCK_CHARS:
                    continue
                block_rect = fitz.Rect(block[:4])
                center_x = (block[0] + block[2]) / 2
                center_y = (block[1] + block[3]) / 2
                center_pt = fitz.Point(center_x, center_y)
                # Exclude if center falls inside any table bbox (reliable for table cells
                # even when pdfplumber/PyMuPDF coords differ slightly)
                if any(tr.contains(center_pt) for tr in table_fitz_rects):
                    continue
                # Also exclude by overlap threshold (catches partial overlaps)
                if any(_overlap_ratio(block_rect, tr) > _TABLE_OVERLAP_THRESH
                       for tr in table_fitz_rects):
                    continue
                if any(_overlap_ratio(block_rect, vr) > _VISUAL_OVERLAP_THRESH
                       for vr in visual_fitz_rects):
                    continue
                text_char_count += len(block_text)
                text_elements.append({
                    "type": "text",
                    "bbox": list(block[:4]),
                    "char_count": len(block_text),
                })

            has_text   = text_char_count >= _MIN_TEXT_CHARS
            has_table  = bool(tables_data)
            has_visual = bool(visual_elements)

            # ── Step 4: page_type from element presence ───────────────────────
            # full_page_image: any page with visual + at least one other element type
            # (table, text, or multiple visuals).  Per product directive: mixed-content
            # pages are captured as a single high-res image and described by Gemini,
            # rather than being parsed element-by-element.  Simple single-type pages
            # (pure text, pure table, single standalone visual) keep element-based flow.
            multi_visual = len(visual_elements) > 1
            if not (has_text or has_table or has_visual):
                page_type, layer = "skip", "element_detect"
            elif has_visual and (has_table or has_text or multi_visual):
                page_type, layer = "full_page_image", "element_detect"
            elif has_visual:
                page_type, layer = "multimodal", "element_detect"
            elif has_table and has_text:
                page_type, layer = "mixed", "element_detect"
            elif has_table:
                page_type, layer = "table", "element_detect"
            else:
                page_type, layer = "text", "element_detect"

            # For full_page_image pages, collapse detected elements into a single
            # full-page element.  Individual table/visual/text elements are still
            # detected above (so image_ratio / has_tables are correct), but the
            # pipeline only sees one element and renders the entire page.
            if page_type == "full_page_image":
                all_elements: list = [{
                    "type": "full_page_image",
                    "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
                }]
            else:
                # Assemble element list (tables first, then visuals, then text)
                all_elements = tables_data + visual_elements + (
                    text_elements if has_text else []
                )
            if not all_elements:
                all_elements = [{"type": "none"}]

            # image_ratio: proportion of page covered by detected visual regions
            visual_area = sum(fitz.Rect(v["bbox"]).get_area() for v in visual_elements)
            image_ratio = min(visual_area / page_area, 1.0)

            rec = _processing_rec(page_type)

            elem_summary = (
                f"{len(tables_data)}T / {len(visual_elements)}V / "
                f"{len(text_elements)} text-blks  chars={text_char_count}"
            )
            logger.info(f"Page {page_num:3d} | {page_type:<13s} | {elem_summary}")

            results.append(PageClassification(
                page_number=page_num,
                page_type=page_type,
                text_ratio=round(text_ratio, 3),
                image_ratio=round(image_ratio, 3),
                has_tables=has_table,
                detected_elements=all_elements,
                processing_recommendation=rec,
                estimated_text_tokens=estimated_tokens,
                layer_used=layer,
            ))
            fitz_page = None

    fitz_doc.close()
    return results


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _cluster_rects(rects: list, gap: int = 20) -> list:
    """
    Merge a list of fitz.Rects into clusters where members are within `gap` points
    of each other. Each cluster is represented as the bounding rect of all its members.
    """
    if not rects:
        return []
    clusters = [fitz.Rect(r) for r in rects]
    merged = True
    while merged:
        merged = False
        result: list[fitz.Rect] = []
        used: set[int] = set()
        for i, cur in enumerate(clusters):
            if i in used:
                continue
            expanded = fitz.Rect(
                cur.x0 - gap, cur.y0 - gap,
                cur.x1 + gap, cur.y1 + gap,
            )
            for j in range(i + 1, len(clusters)):
                if j in used:
                    continue
                if expanded.intersects(clusters[j]):
                    cur = cur | clusters[j]
                    expanded = fitz.Rect(
                        cur.x0 - gap, cur.y0 - gap,
                        cur.x1 + gap, cur.y1 + gap,
                    )
                    used.add(j)
                    merged = True
            result.append(cur)
        clusters = result
    return clusters


def _cluster_only_overlapping(rects: list, overlap_threshold: float = 0.5) -> list:
    """
    Cluster rectangles ONLY if they overlap significantly (share >overlap_threshold
    of the smaller rect's area). Unlike _cluster_rects, this does NOT merge nearby
    rects — only truly overlapping ones. Used for vector drawings so that distinct
    chart regions are not merged into a single bounding box.
    Returns list of merged fitz.Rect objects.
    """
    if not rects:
        return []

    clusters = [[fitz.Rect(r)] for r in rects]

    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            if merged:
                break
            for j in range(i + 1, len(clusters)):
                found = False
                for r1 in clusters[i]:
                    for r2 in clusters[j]:
                        intersection = r1 & r2
                        if not intersection.is_empty:
                            min_area = min(r1.get_area(), r2.get_area())
                            if min_area > 0 and intersection.get_area() / min_area > overlap_threshold:
                                clusters[i].extend(clusters[j])
                                clusters.pop(j)
                                merged = True
                                found = True
                                break
                    if found:
                        break
                if merged:
                    break

    result = []
    for cluster in clusters:
        if not cluster:
            continue
        bbox = cluster[0]
        for r in cluster[1:]:
            bbox = bbox | r
        result.append(bbox)
    return result


def _overlap_ratio(r1: fitz.Rect, r2: fitz.Rect) -> float:
    """Fraction of r1's area that overlaps with r2. Returns 0.0 if r1 has no area."""
    r1_area = r1.get_area()
    if r1_area < 1.0:
        return 0.0
    inter = r1 & r2
    if inter.is_empty:
        return 0.0
    return inter.get_area() / r1_area


# ── Shared helpers (unchanged) ────────────────────────────────────────────────

def _make_skip(page_num: int) -> PageClassification:
    return PageClassification(
        page_number=page_num, page_type="skip",
        text_ratio=0.0, image_ratio=0.0, has_tables=False,
        detected_elements=[{"type": "none"}],
        processing_recommendation="skip",
        estimated_text_tokens=0, layer_used="element_detect",
    )


def _processing_rec(page_type: str) -> str:
    return {
        "text":             "embed_text_only",
        "table":            "pdfplumber_table_extract",
        "multimodal":       "gemini_vision",
        "mixed":            "element_based",
        "full_page_image":  "gemini_full_page",
        "skip":             "skip",
        "structured_text":  "embed_text_only",
    }.get(page_type, "embed_text_only")


def _try_split_cluster(
    fitz_page,
    cluster: fitz.Rect,
    page_area: float,
    split_threshold: float = 0.40,
    min_sub_ratio: float = 0.05,
    min_band_width: int = 10,
) -> list:
    """
    For large visual clusters (> split_threshold of page area), attempt to find
    natural whitespace bands (rows or columns that are ≥95% white) and split there.
    Returns list of sub-Rects if a clean split is found, else [cluster] unchanged.
    Any sub-rect below min_sub_ratio of page area is discarded.

    Increased split_threshold to 0.40 (40% page) to avoid splitting bar charts.
    min_band_width=10 prevents splitting on thin bar spacing.
    """
    if cluster.get_area() / max(page_area, 1) < split_threshold:
        return [cluster]

    # Aspect ratio guard: don't split reasonable chart dimensions
    # Typical charts: landscape (2:1) to portrait (1:2)
    width = cluster.x1 - cluster.x0
    height = cluster.y1 - cluster.y0
    if height > 0:
        aspect_ratio = width / height
        if 0.4 <= aspect_ratio <= 3.0:
            # Reasonable single-chart aspect ratio → don't split
            return [cluster]
    try:
        scale = 0.5
        pix = fitz_page.get_pixmap(
            matrix=fitz.Matrix(scale, scale), clip=cluster, colorspace=fitz.csGRAY
        )
        w, h = pix.width, pix.height
        if w < 10 or h < 10:
            del pix
            return [cluster]
        samples = bytes(pix.samples)
        del pix
    except Exception:
        return [cluster]

    def _row_white(i: int) -> bool:
        row = samples[i * w: i * w + w]
        return sum(b > 240 for b in row) / w > 0.95 if w else True

    def _col_white(j: int) -> bool:
        col = [samples[r * w + j] for r in range(h)]
        return sum(b > 240 for b in col) / h > 0.95 if h else True

    def _find_splits(is_white_fn, size: int, min_width: int):
        """Find midpoints of white bands (≥min_width pixels wide) between content."""
        in_band = False
        band_start = 0
        splits: list[float] = []
        for i in range(size):
            if is_white_fn(i) and not in_band:
                band_start = i
                in_band = True
            elif not is_white_fn(i) and in_band:
                if i - band_start >= min_width:
                    splits.append((band_start + i) / 2)
                in_band = False
        return splits

    def _build_sub_rects(splits, lo, hi, scale, is_horizontal):
        boundaries = [lo] + [lo + s / scale for s in splits] + [hi]
        subs = []
        for k in range(len(boundaries) - 1):
            if is_horizontal:
                sr = fitz.Rect(cluster.x0, boundaries[k], cluster.x1, boundaries[k + 1])
            else:
                sr = fitz.Rect(boundaries[k], cluster.y0, boundaries[k + 1], cluster.y1)
            if sr.get_area() >= page_area * min_sub_ratio:
                subs.append(sr)
        return subs

    # Try horizontal split first
    h_splits = _find_splits(_row_white, h, min_band_width)
    if h_splits:
        subs = _build_sub_rects(h_splits, cluster.y0, cluster.y1, scale, True)
        if len(subs) > 1:
            logger.debug(f"Split large cluster into {len(subs)} horizontal sub-regions")
            return subs

    # Try vertical split
    v_splits = _find_splits(_col_white, w, min_band_width)
    if v_splits:
        subs = _build_sub_rects(v_splits, cluster.x0, cluster.x1, scale, False)
        if len(subs) > 1:
            logger.debug(f"Split large cluster into {len(subs)} vertical sub-regions")
            return subs

    return [cluster]


def _detect_whitespace_tables(words: list) -> list:
    """
    Detect whitespace-aligned tables (no borders/lines) from pdfplumber extracted words.

    Algorithm:
      1. Group words into raw lines by y-coordinate (3pt tolerance).
      2. First pass: compute column centers from all words (30pt gap → distinct columns).
      3. Assign words to columns, build logical rows.
         Consecutive raw lines are merged into the same logical row only if:
         - gap between them is < 8pt, AND
         - the next line introduces no NEW column positions (it's a cell continuation).
      4. Aligned row = row with words in ≥2 distinct columns.
      5. Column consistency: each column center must appear in ≥40% of aligned rows.
      6. CID artifact filter: skip rows with "(cid:" or average cell length < 3 chars.
      7. If ≥3 aligned rows AND ≥2 consistent columns → detected as a table.

    Returns list of {"bbox": [x0, y0, x1, y1], "rows": [[cell, ...], ...]}
    """
    if not words:
        return []

    # Step 1: group words into raw lines by y-coordinate (3pt tolerance)
    raw_lines: dict[int, list] = {}
    for word in words:
        y_key = int(round(word.get("top", 0) / 3) * 3)
        raw_lines.setdefault(y_key, []).append(word)

    if len(raw_lines) < 3:
        return []

    sorted_raw = [raw_lines[y] for y in sorted(raw_lines.keys())]

    # Step 2: cluster ALL x0 positions to find column centers (30pt gap)
    all_x0 = sorted(w["x0"] for line in sorted_raw for w in line)
    if not all_x0:
        return []

    col_centers: list[float] = []
    cl: list[float] = [all_x0[0]]
    for x in all_x0[1:]:
        if x - cl[-1] <= 30:
            cl.append(x)
        else:
            col_centers.append(sum(cl) / len(cl))
            cl = [x]
    col_centers.append(sum(cl) / len(cl))

    if len(col_centers) < 2:
        return []

    def _col_of(x: float) -> int:
        for ci, cx in enumerate(col_centers):
            if abs(x - cx) <= 15:
                return ci
        return -1

    # Step 3: build logical rows with smart multi-line cell merging.
    # Logical rows: list of (word_list, col_words_dict)
    logical_rows: list[tuple[list, dict]] = []

    for line in sorted_raw:
        col_words: dict[int, list[str]] = {}
        for word in line:
            ci = _col_of(word["x0"])
            if ci >= 0:
                col_words.setdefault(ci, []).append(word.get("text", ""))

        # Attempt to merge into previous logical row if it's a cell continuation:
        # - gap < 8pt between bottom of previous and top of current
        # - current line introduces NO NEW column positions
        merged = False
        if logical_rows and col_words:
            prev_words, prev_cols = logical_rows[-1]
            prev_bottom = max(w.get("bottom", 0) for w in prev_words)
            cur_top = min(w.get("top", 0) for w in line)
            gap = cur_top - prev_bottom
            new_cols = set(col_words.keys()) - set(prev_cols.keys())
            if gap < 8 and not new_cols:
                for ci, texts in col_words.items():
                    prev_cols[ci].extend(texts)
                prev_words.extend(line)
                merged = True

        if not merged:
            logical_rows.append((list(line), col_words))

    # Step 4-6: extract aligned rows with quality filters
    aligned_rows: list[list[str]] = []
    aligned_words: list = []
    col_counts: dict[int, int] = {}   # how many rows each column appears in

    for row_words, col_words in logical_rows:
        if len(col_words) < 2:
            continue
        cells = [" ".join(col_words.get(ci, [""])) for ci in range(len(col_centers))]
        # CID font artifact filter
        if any("(cid:" in cell for cell in cells):
            continue
        # Very short average cell length = likely CID-split single chars, not real data
        nonempty = [c for c in cells if c.strip()]
        if nonempty and (sum(len(c) for c in nonempty) / len(nonempty)) < 3:
            continue
        aligned_rows.append(cells)
        aligned_words.extend(row_words)
        for ci in col_words:
            col_counts[ci] = col_counts.get(ci, 0) + 1

    if len(aligned_rows) < 3:
        return []

    # Step 7: column consistency — each column must appear in ≥40% of aligned rows
    n_rows = len(aligned_rows)
    consistent_cols = {ci for ci, cnt in col_counts.items() if cnt / n_rows >= 0.40}
    if len(consistent_cols) < 2:
        return []

    if not aligned_words:
        return []

    x0 = min(w["x0"] for w in aligned_words)
    y0 = min(w["top"] for w in aligned_words)
    x1 = max(w["x1"] for w in aligned_words)
    y1 = max(w["bottom"] for w in aligned_words)

    return [{"bbox": [x0, y0, x1, y1], "rows": aligned_rows}]


def classify_non_pdf(
    original_format: str,
    page_count: int,
    sheets_info: Optional[list] = None,
) -> list[PageClassification]:
    """Classify non-PDF logical pages (Excel sheets, YAML, JPEG/PNG). Unchanged."""
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
        elif original_format in ("jpeg", "jpg", "png", "bmp", "tiff", "gif", "webp"):
            logger.info(f"Page {page_num:3d} | multimodal    | Image file")
            results.append(PageClassification(
                page_number=page_num, page_type="multimodal",
                text_ratio=0.0, image_ratio=1.0, has_tables=False,
                detected_elements=["image"],
                processing_recommendation="gemini_vision",
                estimated_text_tokens=0, layer_used="non_pdf",
            ))
    return results
