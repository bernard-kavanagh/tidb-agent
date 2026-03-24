"""
Semantic case study matching for leads.
Embeddings are computed once on first call and cached in memory.
"""
from __future__ import annotations
import math

from .case_studies import CASE_STUDIES
from .embeddings import embed

_case_embeddings: list[list[float]] | None = None


def _get_case_embeddings() -> list[list[float]]:
    global _case_embeddings
    if _case_embeddings is None:
        _case_embeddings = [embed(cs["summary"]) for cs in CASE_STUDIES]
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
    """
    case_embs = _get_case_embeddings()
    scores = [(i, _cosine(lead_embedding, ce)) for i, ce in enumerate(case_embs)]
    scores.sort(key=lambda x: x[1], reverse=True)
    results = []
    for i, sim in scores[:top_k]:
        if sim < 0.3:
            break
        cs = CASE_STUDIES[i]
        results.append({
            "title":      cs["title"],
            "url":        cs["url"],
            "similarity": round(sim * 100),
        })
    return results
