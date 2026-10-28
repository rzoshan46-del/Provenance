"""app/integrity/signals.py — AI marker heuristic signals.

MOCKED heuristic: production would use a vetted AI-content classifier.
"""
from typing import List

_STRONG_AI_MARKERS = [
    "as an ai language model",
    "as a large language model",
    "i'm sorry, but i can't",
    "certainly! here",
    "regenerate response",
]


def ai_markers(text: str) -> List[str]:
    """Scan text for strong AI language markers (case-insensitive).
    
    Returns list of matched marker strings found.
    """
    # MOCKED heuristic: production would use a vetted AI-content classifier
    if not text:
        return []

    lower_text = text.lower()
    found: List[str] = []
    for marker in _STRONG_AI_MARKERS:
        if marker in lower_text:
            found.append(marker)

    return found
