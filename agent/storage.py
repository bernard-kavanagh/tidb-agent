"""
TiDB Cloud (MySQL-compatible) storage layer.
Uses PyMySQL with SSL for TiDB Cloud connections.
"""
import json
import certifi
import pymysql
import pymysql.cursors
from contextlib import contextmanager
import urllib.parse
from urllib.parse import urlparse, parse_qs

from .config import TIDB_CONNECTION_STRING
from .embeddings import embed_lead, lead_text


def _parse_dsn(dsn: str) -> dict:
    """Parse a mysql:// DSN into pymysql.connect() kwargs."""
    url = urlparse(dsn)
    qs  = parse_qs(url.query)

    kwargs: dict = {
        "host":    url.hostname,
        "port":    url.port or 4000,
        "user":    url.username,
        "password": url.password or "",
        "database": url.path.lstrip("/") or "test",
        "charset":  "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
    }

    # Enable SSL for TiDB Cloud (any ssl_* param in the DSN triggers it)
    ssl_keys = {k for k in qs if k.startswith("ssl")}
    if ssl_keys or url.hostname and "tidb" in url.hostname:
        kwargs["ssl"] = {"ca": certifi.where()}

    return kwargs


def get_conn():
    return pymysql.connect(**_parse_dsn(TIDB_CONNECTION_STRING))


@contextmanager
def db_conn():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_lead(
    conn,
    company_name: str,
    website: str,
    country: str,
    region: str,
    geo: str,
    analysis: dict,
    source_url: str,
) -> int:
    """
    Insert or update a lead. Returns the lead id.
    Uses ON DUPLICATE KEY UPDATE on the (company_name, country) unique key.
    The `id = LAST_INSERT_ID(id)` trick ensures cursor.lastrowid is correct
    for both INSERT and UPDATE paths.
    """
    # Generate embedding from the analysis fields
    vec = embed_lead(analysis)
    vec_str = "[" + ",".join(f"{v:.6f}" for v in vec) + "]" if vec else None

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO leads
                (company_name, website, country, region, geo, industry, company_size,
                 description, tidb_pain, tidb_use_case, fit_score, source_url,
                 embedding, outreach_recommendation, discovery_country, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                id                      = LAST_INSERT_ID(id),
                website                 = VALUES(website),
                region                  = VALUES(region),
                geo                     = VALUES(geo),
                industry                = VALUES(industry),
                company_size            = VALUES(company_size),
                description             = VALUES(description),
                tidb_pain               = VALUES(tidb_pain),
                tidb_use_case           = VALUES(tidb_use_case),
                fit_score               = VALUES(fit_score),
                source_url              = VALUES(source_url),
                embedding               = VALUES(embedding),
                outreach_recommendation = VALUES(outreach_recommendation),
                discovery_country       = VALUES(discovery_country),
                updated_at              = NOW()
        """, (
            company_name, website, country, region, geo,
            analysis.get("industry"),
            analysis.get("company_size"),
            analysis.get("description"),
            analysis.get("tidb_pain"),
            analysis.get("tidb_use_case"),
            analysis.get("fit_score"),
            source_url,
            vec_str,
            analysis.get("outreach_recommendation"),
            analysis.get("discovery_country"),
        ))
        lead_id = cur.lastrowid

        # Replace contacts for this lead
        cur.execute("DELETE FROM contacts WHERE lead_id = %s", (lead_id,))
        for role in analysis.get("icp_contacts", []):
            q = urllib.parse.quote_plus(f"{role} {company_name}")
            li_url = f"https://www.linkedin.com/search/results/people/?keywords={q}&origin=GLOBAL_SEARCH_HEADER"
            cur.execute(
                "INSERT INTO contacts (lead_id, role, linkedin_url) VALUES (%s, %s, %s)",
                (lead_id, role, li_url),
            )

    return lead_id


def get_leads(
    conn,
    country: str | None = None,
    region:  str | None = None,
    geo:     str | None = None,
    min_score: int = 1,
    status: str | None = None,
) -> list[dict]:
    with conn.cursor() as cur:
        query = """
            SELECT
                l.id, l.company_name, l.website, l.country, l.region, l.geo,
                l.industry, l.company_size, l.description, l.tidb_pain, l.tidb_use_case,
                l.fit_score, l.status, l.created_at, l.embedding, l.outreach_recommendation,
                COALESCE(JSON_ARRAYAGG(c.role), JSON_ARRAY()) AS contact_roles,
                COALESCE(JSON_ARRAYAGG(c.linkedin_url), JSON_ARRAY()) AS contact_links
            FROM leads l
            LEFT JOIN contacts c ON c.lead_id = l.id
            WHERE l.fit_score >= %s
        """
        params: list = [min_score]

        if geo:
            query += " AND l.geo = %s"
            params.append(geo)
        if country:
            query += " AND l.country = %s"
            params.append(country)
        if region:
            query += " AND l.region = %s"
            params.append(region)
        if status:
            query += " AND l.status = %s"
            params.append(status)

        query += " GROUP BY l.id ORDER BY l.fit_score DESC, l.company_name"
        cur.execute(query, params)
        rows = cur.fetchall()

    result = []
    for row in rows:
        row = dict(row)
        # JSON_ARRAYAGG returns a string in PyMySQL — parse it
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


def get_countries_summary(conn) -> list[dict]:
    """Returns per-country lead counts grouped by geo + region."""
    with conn.cursor() as cur:
        # MySQL/TiDB doesn't support COUNT(*) FILTER (WHERE ...) — use SUM(CASE ...)
        cur.execute("""
            SELECT
                COALESCE(geo, 'EMEA')                                     AS geo,
                region,
                country,
                COUNT(*)                                                  AS total,
                SUM(CASE WHEN fit_score >= 8 THEN 1 ELSE 0 END)          AS hot,
                SUM(CASE WHEN status = 'contacted' THEN 1 ELSE 0 END)    AS contacted,
                ROUND(AVG(fit_score), 1)                                  AS avg_score
            FROM leads
            GROUP BY geo, region, country
            ORDER BY geo, region, country
        """)
        return [dict(r) for r in cur.fetchall()]


def update_lead_status(conn, lead_id: int, status: str):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE leads SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, lead_id),
        )
