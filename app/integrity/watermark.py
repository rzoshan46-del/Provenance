"""Per-viewer invisible watermarking and extraction.

MOCKED robustness: production would use robust fingerprinting.
"""

from collections import Counter
import re
from typing import Any, Dict, Optional

# Characters used for watermarking
DELIMITER = "\u2060"  # U+2060 WORD JOINER
BIT_0 = "\u200b"      # U+200B ZERO WIDTH SPACE
BIT_1 = "\u200c"      # U+200C ZERO WIDTH NON-JOINER


def encode_marker(user_id: int) -> str:
    """Encode user_id as a 16-bit integer with an 8-bit checksum wrapped in delimiters."""
    uid = user_id & 0xFFFF
    hi = (uid >> 8) & 0xFF
    lo = uid & 0xFF
    checksum = (hi + lo) % 256

    # 16 bits for user_id + 8 bits for checksum = 24 bits
    bits = []
    for i in range(16):
        bits.append((uid >> (15 - i)) & 1)
    for i in range(8):
        bits.append((checksum >> (7 - i)) & 1)

    chars = [BIT_1 if b == 1 else BIT_0 for b in bits]
    return f"{DELIMITER}{''.join(chars)}{DELIMITER}"


def apply(text: str, user_id: int) -> str:
    """Insert a marker after the first word of every non-empty line.

    If a line consists of a single word, the marker is appended.
    Empty text is unchanged.
    """
    if not text:
        return text

    marker = encode_marker(user_id)
    lines = text.split("\n")
    processed = []
    for line in lines:
        if not line or line.isspace():
            processed.append(line)
            continue
        m = re.match(r"^(\s*\S+)(.*)$", line)
        if m:
            first_word_prefix = m.group(1)
            rest_of_line = m.group(2)
            processed.append(first_word_prefix + marker + rest_of_line)
        else:
            processed.append(line)

    return "\n".join(processed)


def extract(text: str) -> Dict[str, Any]:
    """Find all candidate markers and return winning user_id by majority vote.

    Returns dict with keys:
    - found: bool
    - valid: bool
    - user_id: int or None
    - marks_found: int
    - marks_valid: int
    - confidence: float
    """
    if not text:
        return {
            "found": False,
            "valid": False,
            "user_id": None,
            "marks_found": 0,
            "marks_valid": 0,
            "confidence": 0.0,
        }

    # Match anything between delimiters
    candidates = re.findall(rf"{DELIMITER}([^{DELIMITER}]*){DELIMITER}", text)
    marks_found = len(candidates)
    if marks_found == 0:
        return {
            "found": False,
            "valid": False,
            "user_id": None,
            "marks_found": 0,
            "marks_valid": 0,
            "confidence": 0.0,
        }

    valid_votes: Counter = Counter()
    marks_valid = 0

    for cand in candidates:
        if len(cand) != 24:
            continue
        # Ensure all characters are valid bits
        if any(c not in (BIT_0, BIT_1) for c in cand):
            continue

        bits = [1 if c == BIT_1 else 0 for c in cand]
        uid = 0
        for b in bits[:16]:
            uid = (uid << 1) | b
        chk = 0
        for b in bits[16:]:
            chk = (chk << 1) | b

        hi = (uid >> 8) & 0xFF
        lo = uid & 0xFF
        expected_chk = (hi + lo) % 256
        if chk == expected_chk:
            marks_valid += 1
            valid_votes[uid] += 1

    if marks_valid == 0 or not valid_votes:
        return {
            "found": False,
            "valid": False,
            "user_id": None,
            "marks_found": marks_found,
            "marks_valid": marks_valid,
            "confidence": 0.0,
        }

    winner_id, winner_count = valid_votes.most_common(1)[0]
    confidence = round(winner_count / marks_found, 4)

    return {
        "found": True,
        "valid": True,
        "user_id": winner_id,
        "marks_found": marks_found,
        "marks_valid": marks_valid,
        "confidence": confidence,
    }


def strip(text: str) -> str:
    """Remove all zero-width watermarking characters from text."""
    if not text:
        return text
    return re.sub(rf"[{DELIMITER}{BIT_0}{BIT_1}]", "", text)
