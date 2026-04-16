"""
Semantic case study matching for leads.
Embeddings are pre-computed by ~/precompute_embeddings.py and stored in
agent/case_study_embeddings.json. No sentence-transformers needed at runtime.
"""
from __future__ import annotations
import json
import math
from pathlib import Path

from .case_studies import CASE_STUDIES

_EMBEDDINGS_FILE = Path(__file__).parent / "case_study_embeddings.json"

_case_embeddings: list[list[float]] | None = None


def _load_embeddings() -> list[list[float]]:
    if not _EMBEDDINGS_FILE.exists():
        return []
    try:
        data = json.loads(_EMBEDDINGS_FILE.read_text())
        return [entry["embedding"] for entry in data if entry.get("embedding")]
    except Exception:
        return []


def _get_case_embeddings() -> list[list[float]]:
    global _case_embeddings
    if _case_embeddings is None:
        _case_embeddings = _load_embeddings()
    return _case_embeddings


def _cosine(a: list[float], b: list[float]) -> float:
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_case_studies(lead_embedding: list[float], top_k: int = 2) -> list[dict]:
    """
    Return the top_k most similar case studies for a lead (similarity > 0.3).
    Each result: {'title': str, 'url': str, 'similarity': int (0-100)}.
    Requires agent/case_study_embeddings.json (run ~/precompute_embeddings.py once).
    """
    case_embs = _get_case_embeddings()
    if not case_embs:
        return []
    scores = [(i, _cosine(lead_embedding, ce)) for i, ce in enumerate(case_embs)]
    scores.sort(key=lambda x: x[1], reverse=True)
    results = []
    for i, sim in scores[:top_k]:
        if sim < 0.3:
            break
        cs = CASE_STUDIES[i] if i < len(CASE_STUDIES) else {}
        if not cs:
            continue
        results.append(dict(
            title=cs["title"],
            url=cs["url"],
            similarity=round(sim * 100),
        ))
    return results
