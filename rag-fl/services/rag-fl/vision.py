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
    "You are analyzing a full document page that contains mixed content. "
    "Describe this page comprehensively, including:\n"
    "- All text content (headings, paragraphs, labels)\n"
    "- All tables: reproduce the full structure with column headers and every data row\n"
    "- All charts/graphs: type, axis labels, data values and trends\n"
    "- All diagrams/flowcharts: components and relationships\n"
    "- Spatial layout: what appears at the top, middle, and bottom of the page\n"
    "- Key insights or patterns visible across elements\n\n"
    "Format your response as a cohesive description that captures the page's "
    "complete information so that it can be retrieved and used as context for "
    "answering questions about its content."
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
