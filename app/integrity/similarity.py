"""app/integrity/similarity.py — Deterministic similarity comparison.

Pure functions for tokenization, shingling, and similarity comparison.
SPEC.md §20:
- Tokenize: lower-case, regex [a-z0-9]+
- Shingles: 3-word tuples
- compare(new_text, other_text) -> {jaccard, cosine, containment, score}
- FLAG_THRESHOLD = 0.6
"""
from collections import Counter
import math
import re
from typing import Any, Dict, List, Set, Tuple

FLAG_THRESHOLD: float = 0.6


def tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def shingles(tokens: List[str], k: int = 3) -> Set[Tuple[str, ...]]:
    """Return set of k-word shingles as tuples."""
    if len(tokens) < k:
        return set()
    return {tuple(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def compare(new_text: str, other_text: str) -> Dict[str, float]:
    """Compare two texts for similarity and containment.
    
    Returns:
        {
            "jaccard": float,
            "cosine": float,
            "containment": float,
            "score": float,
        }
    """
    toks_a = tokenize(new_text)
    toks_b = tokenize(other_text)

    # Texts with fewer than 3 tokens score 0
    if len(toks_a) < 3 or len(toks_b) < 3:
        return {
            "jaccard": 0.0,
            "cosine": 0.0,
            "containment": 0.0,
            "score": 0.0,
        }

    # 1. Shingle Jaccard
    sh_a = shingles(toks_a, 3)
    sh_b = shingles(toks_b, 3)
    union_sh = sh_a | sh_b
    inter_sh = sh_a & sh_b

    jaccard = (len(inter_sh) / len(union_sh)) if union_sh else 0.0

    # 2. Token cosine
    counts_a = Counter(toks_a)
    counts_b = Counter(toks_b)
    dot = sum(counts_a[t] * counts_b[t] for t in (set(counts_a) & set(counts_b)))
    norm_a = math.sqrt(sum(c * c for c in counts_a.values()))
    norm_b = math.sqrt(sum(c * c for c in counts_b.values()))
    cosine = (dot / (norm_a * norm_b)) if (norm_a > 0 and norm_b > 0) else 0.0

    # 3. Containment = |A ∩ B| / |A| where A = new text's shingles (only when |A| >= 5)
    # Also support containment when other_text is pasted inside new_text (|A ∩ B| / |B| when |B| >= 5)
    cont_a = (len(inter_sh) / len(sh_a)) if len(sh_a) >= 5 else 0.0
    cont_b = (len(inter_sh) / len(sh_b)) if len(sh_b) >= 5 else 0.0
    containment = max(cont_a, cont_b)

    score = max(0.5 * jaccard + 0.5 * cosine, containment)
    score = min(max(score, 0.0), 1.0)

    return {
        "jaccard": round(jaccard, 4),
        "cosine": round(cosine, 4),
        "containment": round(containment, 4),
        "score": round(score, 4),
    }
