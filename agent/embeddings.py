"""
Embedding generation and hybrid semantic search for leads.

Uses sentence-transformers (all-MiniLM-L6-v2, 384 dims) — runs locally, no API key needed.
TiDB stores the vectors natively and searches with VEC_COSINE_DISTANCE + HNSW index.

Hybrid search = keyword (LIKE) OR vector similarity, ranked by combined score.
"""
import json
from typing import Optional

_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed(text: str) -> list[float]:
    """Return a 384-dim embedding for the given text."""
    model = _get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def lead_text(lead: dict) -> str:
    """Concatenate the fields we embed for a lead."""
    parts = [
        lead.get("tidb_pain") or "",
        lead.get("tidb_use_case") or "",
        lead.get("description") or "",
        lead.get("industry") or "",
    ]
    return " | ".join(p for p in parts if p).strip()


def embed_lead(lead: dict) -> list[float] | None:
    text = lead_text(lead)
    if not text:
        return None
    return embed(text)


def backfill_embeddings(conn) -> tuple[int, int]:
    """
    Generate and store embeddings for all leads that don't have one yet.
    Returns (updated, skipped).
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, tidb_pain, tidb_use_case, description, industry
            FROM leads
            WHERE embedding IS NULL
        """)
        rows = cur.fetchall()

    updated = 0
    skipped = 0
    for row in rows:
        row = dict(row)
        vec = embed_lead(row)
        if vec is None:
            skipped += 1
            continue
        vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]"
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE leads SET embedding = %s WHERE id = %s",
                (vec_str, row["id"]),
            )
        conn.commit()
        updated += 1

    return updated, skipped


def hybrid_search(
    conn,
    query: str,
    top_k: int = 20,
    min_score: int = 1,
    geo: str | None = None,
    country: str | None = None,
    region: str | None = None,
) -> list[dict]:
    """
    Hybrid search: combines vector cosine similarity with keyword matching.
    Returns leads ranked by relevance.
    """
    query_vec = embed(query)
    vec_str = "[" + ",".join(f"{v:.6f}" for v in query_vec) + "]"

    keyword = f"%{query}%"

    conditions = ["l.fit_score >= %s"]
    params: list = [min_score]

    if geo:
        conditions.append("l.geo = %s")
        params.append(geo)
    if country:
        conditions.append("l.country = %s")
        params.append(country)
    if region:
        conditions.append("l.region = %s")
        params.append(region)

    where = " AND ".join(conditions)

    # Vector similarity search (cosine distance → similarity = 1 - distance)
    # Combined with keyword bonus for transparent ranking
    sql = f"""
        SELECT
            l.id, l.company_name, l.website, l.country, l.region,
            l.industry, l.company_size, l.description,
            l.tidb_pain, l.tidb_use_case, l.fit_score, l.status, l.created_at,
            l.embedding, l.outreach_recommendation,
            COALESCE(JSON_ARRAYAGG(c.role),       JSON_ARRAY()) AS contact_roles,
            COALESCE(JSON_ARRAYAGG(c.linkedin_url), JSON_ARRAY()) AS contact_links,
            ROUND(
                (1 - VEC_COSINE_DISTANCE(l.embedding, %s)) * 100
            , 1) AS similarity_pct,
            CASE
                WHEN l.tidb_pain     LIKE %s THEN 1
                WHEN l.tidb_use_case LIKE %s THEN 1
                WHEN l.description   LIKE %s THEN 1
                ELSE 0
            END AS keyword_hit
        FROM leads l
        LEFT JOIN contacts c ON c.lead_id = l.id
        WHERE {where}
          AND l.embedding IS NOT NULL
        GROUP BY l.id
        ORDER BY
            (1 - VEC_COSINE_DISTANCE(l.embedding, %s)) * 0.7
            + (CASE WHEN l.tidb_pain LIKE %s OR l.tidb_use_case LIKE %s THEN 0.3 ELSE 0 END)
            DESC
        LIMIT %s
    """

    all_params = [vec_str, keyword, keyword, keyword] + params + [vec_str, keyword, keyword, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, all_params)
        rows = cur.fetchall()

    result = []
    for row in rows:
        row = dict(row)
        roles = row.pop("contact_roles", None)
        links = row.pop("contact_links", None)
        if isinstance(roles, str):
            roles = json.loads(roles)
        if isinstance(links, str):
            links = json.loads(links)
        roles = [r for r in (roles or []) if r is not None]
        links = links or []
        row["contacts"] = [
            {"role": r, "linkedin_url": links[i] if i < len(links) else None}
            for i, r in enumerate(roles)
        ]
        result.append(row)

    return result
