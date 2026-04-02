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
        results = hybrid_search(
            conn, query=q, top_k=top_k, min_score=min_score,
            geo=geo or None, country=country or None, region=region or None,
        )
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
