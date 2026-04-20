"""
TiDB Cloud Lead Dashboard - FastAPI backend.

Auth: Google OAuth (Vercel/production) or HTTP Basic (EC2/local fallback).
Set GOOGLE_CLIENT_ID env var to enable Google OAuth; omit for Basic auth.

Run: uvicorn dashboard.main:app --reload --port 8001
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import csv, io, secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from agent.config import TIDB_CONNECTION_STRING, GEO_REGIONS, COUNTRY_GEO, ANTHROPIC_API_KEY
from agent.storage import get_conn, get_leads, get_countries_summary, update_lead_status
from agent.embeddings import hybrid_search, VECTOR_SEARCH_AVAILABLE
from agent.case_matcher import match_case_studies

app = FastAPI(title="TiDB Cloud Lead Pipeline Dashboard")

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SESSION_SECRET       = os.getenv("SESSION_SECRET", "dev-secret-change-in-prod-please")
DASHBOARD_USER       = os.getenv("DASHBOARD_USER", "tidb")
DASHBOARD_PASS       = os.getenv("DASHBOARD_PASS", "tidb2026")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

_oauth = None
if GOOGLE_CLIENT_ID:
    from authlib.integrations.starlette_client import OAuth
    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs=dict(scope="openid email profile"),
    )


class _RequiresLogin(Exception):
    pass


@app.exception_handler(_RequiresLogin)
async def _requires_login_handler(request: Request, exc: _RequiresLogin):
    return RedirectResponse("/login")


if GOOGLE_CLIENT_ID:
    async def get_current_user(request: Request) -> dict:
        user = request.session.get("user")
        if not user:
            raise _RequiresLogin()
        return user
else:
    from fastapi.security import HTTPBasic, HTTPBasicCredentials
    _basic = HTTPBasic()

    async def get_current_user(
        request: Request,
        credentials: HTTPBasicCredentials = Depends(_basic),
    ) -> dict:
        ok = (
            secrets.compare_digest(credentials.username.encode(), DASHBOARD_USER.encode())
            and secrets.compare_digest(credentials.password.encode(), DASHBOARD_PASS.encode())
        )
        if not ok:
            _h = {}
            _h["WWW-Authenticate"] = "Basic"
            raise HTTPException(status_code=401, detail="Unauthorized", headers=_h)
        return dict(email=credentials.username, name=credentials.username, picture="")


static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


if GOOGLE_CLIENT_ID:
    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        return HTMLResponse((static_dir / "login.html").read_text())

    @app.get("/auth/google")
    async def auth_google(request: Request):
        redirect_uri = str(request.base_url).rstrip('/') + '/auth/callback'
        return await _oauth.google.authorize_redirect(request, redirect_uri)

    @app.get("/auth/callback")
    async def auth_callback(request: Request):
        try:
            token = await _oauth.google.authorize_access_token(request)
        except Exception:
            return RedirectResponse("/login?error=auth")
        user_info = token.get("userinfo") or {}
        email = user_info.get("email", "")
        if not email.endswith("@pingcap.com"):
            return RedirectResponse("/login?error=domain")
        request.session["user"] = dict(
            email=email,
            name=user_info.get("name", email),
            picture=user_info.get("picture", ""),
        )
        return RedirectResponse("/")

    @app.get("/auth/logout")
    async def auth_logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login")


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


@app.get("/api/me")
async def api_me(user=Depends(get_current_user)):
    return user


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user=Depends(get_current_user)):
    conn = _db()
    try:
        log_access(conn, user["email"], "login", "", getattr(request.client, "host", ""))
    finally:
        conn.close()
    return HTMLResponse((static_dir / "index.html").read_text())


@app.get("/api/regions")
async def api_regions(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=7200"
    return GEO_REGIONS


@app.get("/api/summary")
async def api_summary(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
    conn = _db()
    try:
        return get_countries_summary(conn)
    finally:
        conn.close()


@app.get("/api/leads")
async def api_leads(
    request: Request,
    user=Depends(get_current_user),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
    min_score: int = Query(1, ge=1, le=10),
    status: str | None = Query(None),
    response: Response = None,
):
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
    conn = _db()
    try:
        detail = str(dict(request.query_params))
        log_access(conn, user["email"], "view_leads", detail, getattr(request.client, "host", ""))
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
    user=Depends(get_current_user),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
    min_score: int = Query(1, ge=1, le=10),
    status: str | None = Query(None),
):
    conn = _db()
    try:
        log_access(conn, user["email"], "export_csv", "", getattr(request.client, "host", ""))
        leads = get_leads(conn, geo=geo, country=country, region=region,
                          min_score=min_score, status=status)
    finally:
        conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Company", "Website", "Country", "Region", "Industry", "Company Size",
        "Description", "TiDB Pain", "TiDB Use Case", "Fit Score", "Status", "ICP Contacts",
    ])
    for lead in leads:
        contacts = "; ".join(
            c.get("role", "") if isinstance(c, dict) else c
            for c in (lead.get("contacts") or [])
        )
        writer.writerow([
            lead.get("company_name", ""), lead.get("website", ""),
            lead.get("country", ""), lead.get("region", ""),
            lead.get("industry", ""), lead.get("company_size", ""),
            lead.get("description", ""), lead.get("tidb_pain", ""),
            lead.get("tidb_use_case", ""), lead.get("fit_score", ""),
            lead.get("status", ""), contacts,
        ])
    output.seek(0)
    filename = "tidb-leads-score" + str(min_score) + "+"
    if country:
        filename += "-" + country.lower().replace(" ", "-")
    elif region:
        filename += "-" + region.lower().replace(" ", "-")
    filename += ".csv"
    disp = "attachment; filename=" + chr(34) + filename + chr(34)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": disp},
    )


@app.get("/api/search")
async def api_search(
    request: Request,
    user=Depends(get_current_user),
    q: str = Query(..., min_length=2),
    top_k: int = Query(20, ge=1, le=100),
    min_score: int = Query(1, ge=1, le=10),
    geo: str | None = Query(None),
    country: str | None = Query(None),
    region: str | None = Query(None),
    response: Response = None,
):
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
    conn = _db()
    try:
        log_access(conn, user["email"], "search", q, getattr(request.client, "host", ""))
        kw = "%" + q + "%"
        kw_filters = ["(company_name LIKE %s OR website LIKE %s)", "fit_score >= %s"]
        kw_params: list = [kw, kw, min_score]
        if geo:     kw_filters.append("geo = %s");     kw_params.append(geo)
        if country: kw_filters.append("country = %s"); kw_params.append(country)
        if region:  kw_filters.append("region = %s");  kw_params.append(region)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM leads WHERE " + " AND ".join(kw_filters) + " LIMIT %s",
                kw_params + [top_k],
            )
            keyword_rows = cur.fetchall() or []
        for r in keyword_rows:
            r["similarity_pct"] = 100
        keyword_ids = set(r["id"] for r in keyword_rows)

        vector_results = hybrid_search(
            conn, query=q, top_k=top_k, min_score=min_score,
            geo=geo or None, country=country or None, region=region or None,
        )
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
async def api_update_status(
    request: Request, lead_id: int, body: dict, user=Depends(get_current_user)
):
    status = body.get("status")
    if status not in ("new", "contacted", "qualified", "disqualified"):
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = _db()
    try:
        log_access(conn, user["email"], "status_change",
                   "lead " + str(lead_id) + " -> " + status,
                   getattr(request.client, "host", ""))
        update_lead_status(conn, lead_id, status)
        conn.commit()
        return dict(ok=True)
    finally:
        conn.close()


from agent.scraper import scrape_text as _scrape_text
from agent.analyzer import analyse_company as _analyse_company
from agent.storage import upsert_lead as _upsert_lead
import agent.storage as _agent_storage
if not VECTOR_SEARCH_AVAILABLE:
    _agent_storage.embed_lead = lambda *a, **kw: None


def _geo_from_tld(url: str) -> str:
    import re
    tld = re.search(r"\.([a-z]{2,6})(?:/|$|\?|#)", url.lower())
    tld = tld.group(1) if tld else "com"
    if tld in ("eu", "de", "fr", "co.uk", "uk", "nl", "es", "it", "pl", "se",
               "no", "dk", "fi", "be", "at", "ch", "ie", "pt", "cz", "hu",
               "ae", "sa", "za", "ng", "ke", "il", "tr"):
        return "EMEA"
    if tld in ("jp", "cn", "sg", "au", "nz", "in", "kr", "hk", "tw", "my",
               "id", "th", "vn", "ph", "pk", "bd"):
        return "APAC"
    return "NAMERICA"


@app.post("/api/lookup")
async def api_lookup(request: Request, body: dict, user=Depends(get_current_user)):
    import re
    import anthropic as _anthropic

    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    domain = re.sub(r"^https?://", "", url.lower())
    domain = re.sub(r"^www\.", "", domain)
    domain = domain.split("/")[0].split("?")[0].split("#")[0]

    conn = _db()
    try:
        log_access(conn, user["email"], "lookup", url, getattr(request.client, "host", ""))
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM leads WHERE website LIKE %s LIMIT 1", ("%" + domain + "%",))
            row = cur.fetchone()
        if row:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            row.pop("embedding", None)
            return dict(source="database", lead=row)
    finally:
        conn.close()

    try:
        geo = _geo_from_tld(url)
        client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        scraped = _scrape_text(url)
        analysis = _analyse_company(client, company_name=domain, website=url,
                                    content=scraped, geo=geo)
        if not analysis or (analysis.get("fit_score") or 0) < 1:
            return dict(source="error", message="Could not analyse this URL")
        hq_country = analysis.get("hq_country") or ""
        geo = COUNTRY_GEO.get(hq_country, geo)
        conn2 = _db()
        try:
            lead_id = _upsert_lead(
                conn2,
                company_name=analysis.get("company_name") or domain,
                website=url,
                country=hq_country or "Manual Entry",
                region="Manual", geo=geo,
                analysis=analysis, source_url=url,
            )
            conn2.commit()
            with conn2.cursor() as cur:
                cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
                lead = cur.fetchone()
            if lead:
                if lead.get("created_at"):
                    lead["created_at"] = lead["created_at"].isoformat()
                lead.pop("embedding", None)
                return dict(source="analysed", lead=lead)
            lead_out = dict(analysis)
            lead_out["website"] = url
            return dict(source="analysed", lead=lead_out)
        finally:
            conn2.close()
    except Exception as e:
        return dict(source="error", message="Could not analyse this URL: " + str(e))



# User Lists

@app.post("/api/lists/add")
async def api_lists_add(request: Request, body: dict, user=Depends(get_current_user)):
    lead_id  = body.get("lead_id")
    notes    = body.get("notes") or None
    username = user["email"]
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_lists (username, lead_id, notes) "
                "VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE notes = VALUES(notes)",
                (username, lead_id, notes),
            )
        conn.commit()
        return dict(ok=True)
    finally:
        conn.close()


@app.delete("/api/lists/remove")
async def api_lists_remove(request: Request, body: dict, user=Depends(get_current_user)):
    lead_id  = body.get("lead_id")
    username = user["email"]
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_lists WHERE username = %s AND lead_id = %s",
                (username, lead_id),
            )
        conn.commit()
        return dict(ok=True)
    finally:
        conn.close()


@app.get("/api/lists/users")
async def api_lists_users(user=Depends(get_current_user)):
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
    user=Depends(get_current_user),
    username: str = Query(...),
):
    import json as _json
    if not username.strip():
        raise HTTPException(status_code=400, detail="username is required")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT l.id, l.company_name, l.website, l.country, l.region, l.geo, "
                "l.industry, l.company_size, l.description, l.tidb_pain, l.tidb_use_case, "
                "l.fit_score, l.status, l.created_at, l.embedding, l.outreach_recommendation, "
                "ul.notes, ul.added_at, "
                "COALESCE(JSON_ARRAYAGG(c.role), JSON_ARRAY()) AS contact_roles, "
                "COALESCE(JSON_ARRAYAGG(c.linkedin_url), JSON_ARRAY()) AS contact_links "
                "FROM user_lists ul "
                "JOIN leads l ON l.id = ul.lead_id "
                "LEFT JOIN contacts c ON c.lead_id = l.id "
                "WHERE ul.username = %s "
                "GROUP BY l.id, ul.notes, ul.added_at "
                "ORDER BY ul.added_at DESC",
                (username.strip(),),
            )
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
                dict(role=r, linkedin_url=links[i] if i < len(links) else None)
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
async def api_access_log(user=Depends(get_current_user)):
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, action, detail, ip_address, created_at "
                "FROM access_log ORDER BY created_at DESC LIMIT 200"
            )
            rows = cur.fetchall()
        for row in rows:
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
        return rows
    finally:
        conn.close()

