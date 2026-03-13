"""
services/rag-fl/vision.py
Gemini 2.0 Flash — describe a rendered page image for embedding.
Includes a circuit breaker: 5 consecutive failures → text-only fallback mode.
"""
import logging
import os
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger("ragfl.vision")

_DESCRIPTION_PROMPT = (
    "Describe this page comprehensively: what is shown, key numbers and labels, "
    "relationships between elements, any data trends visible."
)

_FULL_PAGE_PROMPT = (
    "You are analyzing a full document page that may contain mixed content types. "
    "Provide a comprehensive, structured description in the following format:\n\n"

    "**Overall Description:**\n"
    "Describe what the page shows at a high level (e.g., 'This page presents passenger "
    "demographics data with a comparison table and visualization').\n\n"

    "**Spatial Layout:**\n"
    "- Top: [describe what appears at the top of the page]\n"
    "- Middle: [describe what appears in the middle]\n"
    "- Bottom: [describe what appears at the bottom]\n\n"

    "**Text Content:**\n"
    "IMPORTANT: Extract all visible text EXACTLY as written. Do not paraphrase, summarize, "
    "or add interpretation. Include:\n"
    "- Headings/Titles: [list all headings and titles verbatim]\n"
    "- Paragraphs: [reproduce any paragraph text word-for-word]\n"
    "- Labels/Annotations: [list all labels, captions, and annotations]\n"
    "- Column Labels: [if table present, list all column headers]\n"
    "- Row Labels: [if table present, list all row headers]\n"
    "- Chart Title: [if chart present, exact title]\n"
    "- Chart Axis Labels: [if chart present, x-axis and y-axis labels]\n"
    "- Chart Legend: [if chart present, legend items]\n"
    "- Any other text: [buttons, links, notes, footnotes]\n\n"

    "**Table Structure and Data:**\n"
    "If the page contains ANY table (native table, table as image, screenshot of table, "
    "or table embedded in infographic), reproduce it EXACTLY in Markdown table format:\n\n"
    "| Column1 | Column2 | Column3 | Column4 |\n"
    "|---------|---------|---------|----------|\n"
    "| value1  | value2  | value3  | value4   |\n"
    "| value5  | value6  | value7  | value8   |\n\n"
    "Include ALL rows and columns with their EXACT values. Do not summarize or skip rows.\n\n"

    "**Charts and Graphs:**\n"
    "If the page contains charts, graphs, or plots, describe:\n"
    "- Type: [bar chart, line graph, pie chart, scatter plot, histogram, heatmap, etc.]\n"
    "- Data series: [list all data series shown]\n"
    "- Key values: [notable data points, ranges, or values]\n"
    "- Trends/Patterns: [describe visible trends, comparisons, or insights]\n\n"

    "**Diagrams, Flowcharts, and Schemas:**\n"
    "If the page contains diagrams, flowcharts, process flows, network diagrams, "
    "organizational charts, system architectures, or schemas, describe:\n"
    "- Type: [flowchart, process diagram, network diagram, org chart, architecture diagram, etc.]\n"
    "- Components: [list all boxes, nodes, or elements with their labels]\n"
    "- Relationships: [describe arrows, connections, or flows between components]\n"
    "- Process flow: [if sequential, describe the order/steps]\n\n"

    "**Infographics and Visual Elements:**\n"
    "If the page contains infographics, icons, illustrations, photos, or other visual elements:\n"
    "- Describe the visual content and its purpose\n"
    "- Extract any embedded text or numbers from the visual\n"
    "- Explain what information the visual is conveying\n\n"

    "**Key Insights and Patterns:**\n"
    "Summarize the main insights, patterns, or conclusions that can be drawn from "
    "combining all elements on the page.\n\n"

    "CRITICAL INSTRUCTIONS:\n"
    "1. Extract text VERBATIM - do not paraphrase or add words\n"
    "2. For tables: reproduce COMPLETE structure with ALL rows and columns in Markdown format\n"
    "3. For multiple content types on one page: describe ALL of them separately\n"
    "4. Maintain original formatting, capitalization, and punctuation in extracted text\n"
    "5. If unsure about a value, transcribe what you see without guessing"
)

_EXCEL_CHART_PROMPT = (
    "You are analyzing an Excel sheet rendered as PDF. "
    "IMPORTANT: This sheet's TABLE DATA has already been extracted separately via MarkItDown. "
    "Your ONLY task is to extract VISUAL ELEMENTS (charts, graphs, diagrams).\n\n"

    "DO NOT extract or describe table cells, data rows, or text content.\n"
    "ONLY describe charts, graphs, and visual elements.\n\n"

    "For each chart/graph found, provide:\n"
    "**Chart Type:** [bar chart, line graph, pie chart, scatter plot, combo chart, etc.]\n"
    "**Chart Title:** [exact title if visible]\n"
    "**Axis Labels:**\n"
    "  - X-axis: [label and units]\n"
    "  - Y-axis: [label and units]\n"
    "**Data Series:** [list all series names from legend]\n"
    "**Key Values:** [notable data points, ranges, or peak values]\n"
    "**Trends and Insights:** [describe visible patterns, comparisons, or conclusions]\n\n"

    "If no charts/graphs are visible on this sheet, respond with: 'No charts found.'\n\n"

    "CRITICAL: Ignore all table data, cell values, and text content. "
    "Focus exclusively on visual chart elements."
)

_MODEL = os.getenv("VISION_MODEL", "gemini-2.0-flash")

# Circuit breaker state
_failure_count = 0
_FAILURE_LIMIT = 5
_circuit_open = False  # True = fallback to text-only


def _get_client() -> genai.Client:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return genai.Client(api_key=api_key)


def describe_page_image(image_bytes: bytes) -> Optional[str]:
    """
    Call Gemini to describe a page image.
    Returns description string, or None if circuit is open or call fails.
    """
    global _failure_count, _circuit_open

    if _circuit_open:
        logger.warning("Vision circuit breaker OPEN — skipping Gemini call, needs_vision_retry=true")
        return None

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                _DESCRIPTION_PROMPT,
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            ],
        )
        description = response.text.strip()
        _failure_count = 0  # reset on success
        return description

    except Exception as e:
        _failure_count += 1
        logger.error(f"Gemini Vision call failed ({_failure_count}/{_FAILURE_LIMIT}): {e}")
        if _failure_count >= _FAILURE_LIMIT:
            _circuit_open = True
            logger.error(
                f"Vision circuit breaker OPENED after {_FAILURE_LIMIT} failures. "
                "Remaining multimodal pages will be flagged needs_vision_retry=true."
            )
        return None


def describe_full_page(image_bytes: bytes) -> Optional[str]:
    """
    Call Gemini with a comprehensive full-page prompt.
    Used for full_page_image pages (mixed content: table + visual, multi-visual, etc.)
    Shares the same circuit breaker as describe_page_image().
    """
    global _failure_count, _circuit_open

    if _circuit_open:
        logger.warning("Vision circuit breaker OPEN — skipping full-page Gemini call")
        return None

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                _FULL_PAGE_PROMPT,
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            ],
        )
        description = response.text.strip()
        _failure_count = 0
        return description

    except Exception as e:
        _failure_count += 1
        logger.error(f"Gemini full-page call failed ({_failure_count}/{_FAILURE_LIMIT}): {e}")
        if _failure_count >= _FAILURE_LIMIT:
            _circuit_open = True
            logger.error(
                f"Vision circuit breaker OPENED after {_FAILURE_LIMIT} failures."
            )
        return None


def is_circuit_open() -> bool:
    return _circuit_open


def reset_circuit() -> None:
    """Reset circuit breaker — call this between documents if desired."""
    global _failure_count, _circuit_open
    _failure_count = 0
    _circuit_open = False


def describe_excel_chart(image_bytes: bytes) -> Optional[str]:
    """
    Call Gemini with chart-only prompt for Excel sheets.
    Used when Excel has charts that need visual extraction (MarkItDown handles tables).
    Shares the same circuit breaker as other vision functions.
    """
    global _failure_count, _circuit_open

    if _circuit_open:
        logger.warning("Vision circuit breaker OPEN — skipping Excel chart call")
        return None

    try:
        client = _get_client()
        response = client.models.generate_content(
            model=_MODEL,
            contents=[
                _EXCEL_CHART_PROMPT,
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            ],
        )
        description = response.text.strip()
        _failure_count = 0

        # Return None if no charts found (avoid creating empty chunks)
        if "No charts found" in description:
            return None

        return description

    except Exception as e:
        _failure_count += 1
        logger.error(f"Gemini Excel chart call failed ({_failure_count}/{_FAILURE_LIMIT}): {e}")
        if _failure_count >= _FAILURE_LIMIT:
            _circuit_open = True
            logger.error(f"Vision circuit breaker OPENED after {_FAILURE_LIMIT} failures.")
        return None
