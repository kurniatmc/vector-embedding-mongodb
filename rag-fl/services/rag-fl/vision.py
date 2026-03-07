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
_MODEL = "gemini-2.0-flash"

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


def is_circuit_open() -> bool:
    return _circuit_open


def reset_circuit() -> None:
    """Reset circuit breaker — call this between documents if desired."""
    global _failure_count, _circuit_open
    _failure_count = 0
    _circuit_open = False
