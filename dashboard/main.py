"""
TiDB Cloud Lead Dashboard — FastAPI backend.

Run: uvicorn dashboard.main:app --reload --port 8000
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import csv
import io
import secrets
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from agent.config import TIDB_CONNECTION_STRING, GEO_REGIONS, ANTHROPIC_API_KEY
from agent.storage import get_conn, get_leads, get_countries_summary, update_lead_status
from agent.embeddings import hybrid_search
from agent.case_matcher import match_case_studies

app = FastAPI(title="TiDB Cloud Lead Pipeline Dashboard")
security = HTTPBasic()

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "tidb")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "tidb2026")


def require_auth(credentials: HTTPBasicCredentials = Depends(security)):
    ok = (
        secrets.compare_digest(credentials.username.encode(), DASHBOARD_USER.encode()) and
        secrets.compare_digest(credentials.password.encode(), DASHBOARD_PASS.encode())
    )
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials

# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _db():
    if not TIDB_CONNECTION_STRING:
        raise HTTPException(status_code=503, detail="TIDB_CONNECTION_STRING not configured")
    return get_conn()


def log_access(conn, username: str, action: str, detail: str = "", ip_address: str = ""):
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO access_log (username, action, detail, ip_address) VALUES (%s, %s, %s, %s)",
                (username, action, detail, ip_address),
            )
        conn.commit()
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, auth=Depends(require_auth)):
    conn = _db()
    try:
        log_access(conn, auth.username, "login", "", request.client.host)
    finally:
        conn.close()
    html = (static_dir / "index.html").read_text()
    return HTMLResponse(content=html)


@app.get("/api/regions")
async def api_regions(auth=Depends(require_auth)):
    """Return full geo → sub-region → country hierarchy for all geos."""
    return GEO_REGIONS


@app.get("/api/summary")
async def api_summary(auth=Depends(require_auth)):
    """Per-country lead counts and stats."""
    conn = _db()
    try:
        return get_countries_summary(conn)
    finally:
        conn.close()


@app.get("/api/leads")
async def api_leads(
    request: Request,
    auth=Depends(require_auth),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
    min_score: int = Query(1, ge=1, le=10),
    status: str | None = Query(None),
):
    conn = _db()
    try:
        detail = str(dict(request.query_params))
        log_access(conn, auth.username, "view_leads", detail, request.client.host)
        leads = get_leads(conn, geo=geo, country=country, region=region,
                          min_score=min_score, status=status)
        import json as _json
        for lead in leads:
            if lead.get("created_at"):
                lead["created_at"] = lead["created_at"].isoformat()
            emb = lead.pop("embedding", None)
            try:
                emb_vec = _json.loads(emb) if isinstance(emb, str) else emb
                lead["matched_case_studies"] = match_case_studies(emb_vec) if emb_vec else []
            except Exception:
                lead["matched_case_studies"] = []
        return leads
    finally:
        conn.close()


@app.get("/api/leads/export")
async def api_export(
    request: Request,
    auth=Depends(require_auth),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
    min_score: int = Query(1, ge=1, le=10),
    status: str | None = Query(None),
):
    conn = _db()
    try:
        log_access(conn, auth.username, "export_csv", "", request.client.host)
        leads = get_leads(conn, geo=geo, country=country, region=region,
                          min_score=min_score, status=status)
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Company", "Website", "Country", "Region", "Industry", "Company Size",
        "Description", "TiDB Pain", "TiDB Use Case", "Fit Score", "Status",
        "ICP Contacts"
    ])
    for lead in leads:
        contacts = "; ".join(
            c.get("role", "") if isinstance(c, dict) else c
            for c in (lead.get("contacts") or [])
        )
        writer.writerow([
            lead.get("company_name", ""),
            lead.get("website", ""),
            lead.get("country", ""),
            lead.get("region", ""),
            lead.get("industry", ""),
            lead.get("company_size", ""),
            lead.get("description", ""),
            lead.get("tidb_pain", ""),
            lead.get("tidb_use_case", ""),
            lead.get("fit_score", ""),
            lead.get("status", ""),
            contacts,
        ])

    output.seek(0)
    filename = f"tidb-leads-score{min_score}+"
    if country:
        filename += f"-{country.lower().replace(' ','-')}"
    elif region:
        filename += f"-{region.lower().replace(' ','-')}"
    filename += ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/search")
async def api_search(
    request: Request,
    auth=Depends(require_auth),
    q: str = Query(..., min_length=2),
    top_k: int = Query(20, ge=1, le=100),
    min_score: int = Query(1, ge=1, le=10),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
):
    """
    Hybrid semantic search over leads using TiDB Vector Search.
    Combines VEC_COSINE_DISTANCE similarity with keyword matching.
    """
    conn = _db()
    try:
        log_access(conn, auth.username, "search", q, request.client.host)

        # Keyword matches on company_name / website
        kw = f"%{q}%"
        kw_filters = ["(company_name LIKE %s OR website LIKE %s)", "fit_score >= %s"]
        kw_params: list = [kw, kw, min_score]
        if geo:     kw_filters.append("geo = %s");     kw_params.append(geo)
        if country: kw_filters.append("country = %s"); kw_params.append(country)
        if region:  kw_filters.append("region = %s");  kw_params.append(region)
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM leads WHERE {' AND '.join(kw_filters)} LIMIT %s",
                kw_params + [top_k],
            )
            keyword_rows = cur.fetchall() or []
        for r in keyword_rows:
            r["similarity_pct"] = 100
        keyword_ids = {r["id"] for r in keyword_rows}

        # Vector search
        vector_results = hybrid_search(
            conn, query=q, top_k=top_k, min_score=min_score,
            geo=geo or None, country=country or None, region=region or None,
        )

        # Merge: keyword first, then vector (deduplicated)
        results = list(keyword_rows) + [r for r in vector_results if r["id"] not in keyword_ids]

        import json as _json
        for lead in results:
            if lead.get("created_at"):
                lead["created_at"] = lead["created_at"].isoformat()
            emb = lead.pop("embedding", None)
            try:
                emb_vec = _json.loads(emb) if isinstance(emb, str) else emb
                lead["matched_case_studies"] = match_case_studies(emb_vec) if emb_vec else []
            except Exception:
                lead["matched_case_studies"] = []
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.patch("/api/leads/{lead_id}/status")
async def api_update_status(request: Request, lead_id: int, body: dict, auth=Depends(require_auth)):
    status = body.get("status")
    if status not in ("new", "contacted", "qualified", "disqualified"):
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = _db()
    try:
        log_access(conn, auth.username, "status_change", f"lead {lead_id} -> {status}", request.client.host)
        update_lead_status(conn, lead_id, status)
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.post("/api/lookup")
async def api_lookup(request: Request, body: dict, auth=Depends(require_auth)):
    import re
    import anthropic as _anthropic
    from agent.scraper import scrape_text
    from agent.analyzer import analyse_company
    from agent.storage import upsert_lead

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    geo = (body.get("geo") or "EMEA").upper()
    if geo not in ("EMEA", "NAMERICA", "APAC"):
        geo = "EMEA"

    # Extract domain: strip scheme, www., path
    domain = re.sub(r'^https?://', '', url.lower())
    domain = re.sub(r'^www\.', '', domain)
    domain = domain.split('/')[0].split('?')[0].split('#')[0]

    conn = _db()
    try:
        log_access(conn, auth.username, "lookup", url, request.client.host)

        # Step 1: check database
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM leads WHERE website LIKE %s LIMIT 1",
                (f"%{domain}%",),
            )
            row = cur.fetchone()

        if row:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            row.pop("embedding", None)
            return {"source": "database", "lead": row}
    finally:
        conn.close()

    # Step 2: scrape & analyse
    try:
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        scraped = scrape_text(url)
        analysis = analyse_company(
            client,
            company_name=domain,
            website=url,
            content=scraped,
            geo=geo,
        )
        if not analysis or (analysis.get("fit_score") or 0) < 1:
            return {"source": "error", "message": "Could not analyse this URL"}

        conn2 = _db()
        try:
            lead_id = upsert_lead(
                conn2,
                company_name=analysis.get("company_name") or domain,
                website=url,
                country=analysis.get("hq_country") or "Manual Entry",
                region="Manual",
                geo=geo,
                analysis=analysis,
                source_url=url,
            )
            conn2.commit()
            with conn2.cursor() as cur:
                cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
                lead = cur.fetchone()
            if lead:
                if lead.get("created_at"):
                    lead["created_at"] = lead["created_at"].isoformat()
                lead.pop("embedding", None)
                return {"source": "analysed", "lead": lead}
            return {"source": "analysed", "lead": {**analysis, "website": url}}
        finally:
            conn2.close()
    except Exception as e:
        return {"source": "error", "message": f"Could not analyse this URL: {e}"}




# ── User Lists (My Targets) ───────────────────────────────────────────────

@app.post("/api/lists/add")
async def api_lists_add(request: Request, body: dict, auth=Depends(require_auth)):
    import json as _json
    lead_id  = body.get("lead_id")
    username = (body.get("username") or "").strip()
    notes    = body.get("notes") or None
    if not lead_id or not username:
        raise HTTPException(status_code=400, detail="lead_id and username are required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO user_lists (username, lead_id, notes)
                   VALUES (%s, %s, %s)
                   ON DUPLICATE KEY UPDATE notes = VALUES(notes)""",
                (username, lead_id, notes),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/api/lists/remove")
async def api_lists_remove(request: Request, body: dict, auth=Depends(require_auth)):
    lead_id  = body.get("lead_id")
    username = (body.get("username") or "").strip()
    if not lead_id or not username:
        raise HTTPException(status_code=400, detail="lead_id and username are required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_lists WHERE username = %s AND lead_id = %s",
                (username, lead_id),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/api/lists/users")
async def api_lists_users(auth=Depends(require_auth)):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT username FROM user_lists ORDER BY username")
            rows = cur.fetchall() or []
        return [r["username"] for r in rows]
    finally:
        conn.close()


@app.get("/api/lists")
async def api_lists_get(
    request: Request,
    auth=Depends(require_auth),
    username: str = Query(...),
):
    import json as _json
    if not username.strip():
        raise HTTPException(status_code=400, detail="username is required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    l.id, l.company_name, l.website, l.country, l.region, l.geo,
                    l.industry, l.company_size, l.description, l.tidb_pain, l.tidb_use_case,
                    l.fit_score, l.status, l.created_at, l.embedding, l.outreach_recommendation,
                    ul.notes, ul.added_at,
                    COALESCE(JSON_ARRAYAGG(c.role), JSON_ARRAY()) AS contact_roles,
                    COALESCE(JSON_ARRAYAGG(c.linkedin_url), JSON_ARRAY()) AS contact_links
                FROM user_lists ul
                JOIN leads l ON l.id = ul.lead_id
                LEFT JOIN contacts c ON c.lead_id = l.id
                WHERE ul.username = %s
                GROUP BY l.id, ul.notes, ul.added_at
                ORDER BY ul.added_at DESC
            """, (username.strip(),))
            rows = cur.fetchall() or []
        result = []
        for row in rows:
            row = dict(row)
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            if row.get("added_at"):
                row["added_at"] = row["added_at"].isoformat()
            emb   = row.pop("embedding", None)
            roles = row.pop("contact_roles", None)
            links = row.pop("contact_links", None)
            if isinstance(roles, str): roles = _json.loads(roles)
            if isinstance(links, str): links = _json.loads(links)
            roles = [r for r in (roles or []) if r is not None]
            links = links or []
            row["contacts"] = [
                {"role": r, "linkedin_url": links[i] if i < len(links) else None}
                for i, r in enumerate(roles)
            ]
            try:
                emb_vec = _json.loads(emb) if isinstance(emb, str) else emb
                row["matched_case_studies"] = match_case_studies(emb_vec) if emb_vec else []
            except Exception:
                row["matched_case_studies"] = []
            result.append(row)
        return result
    finally:
        conn.close()


@app.get("/api/access-log")
async def api_access_log(auth=Depends(require_auth)):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, username, action, detail, ip_address, created_at
                FROM access_log
                ORDER BY created_at DESC
                LIMIT 200
            """)
            rows = cur.fetchall()
        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
        return rows
    finally:
        conn.close()
