"""
TiDB Cloud Lead Dashboard - FastAPI backend.

Auth: Google OAuth (Vercel/production) or HTTP Basic (EC2/local fallback).
Set GOOGLE_CLIENT_ID env var to enable Google OAuth; omit for Basic auth.

Run: uvicorn dashboard.main:app --reload --port 8001
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import csv, io, re, secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Depends, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from agent.config import TIDB_CONNECTION_STRING, GEO_REGIONS, COUNTRY_GEO, ANTHROPIC_API_KEY
from agent.storage import get_conn, get_leads, get_countries_summary, update_lead_status
from agent.embeddings import VECTOR_SEARCH_AVAILABLE
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
        countries = get_countries_summary(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(status,'new') AS status, COUNT(*) AS cnt "
                "FROM leads GROUP BY status"
            )
            rows = cur.fetchall() or []
        pipeline = {r["status"]: int(r["cnt"]) for r in rows}
        return {"countries": countries, "pipeline": pipeline}
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
    response.headers["Cache-Control"] = "public, s-maxage=3600, stale-while-revalidate=7200"
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
    min_score: int = Query(1, ge=1, le=10),
    response: Response = None,
):
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
    conn = _db()
    try:
        log_access(conn, user["email"], "search", q, getattr(request.client, "host", ""))
        kw = "%" + q + "%"
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM leads WHERE "
                "(company_name LIKE %s OR website LIKE %s OR industry LIKE %s OR description LIKE %s) "
                "AND fit_score >= %s "
                "ORDER BY fit_score DESC LIMIT 100",
                [kw, kw, kw, kw, min_score],
            )
            results = cur.fetchall() or []
        for lead in results:
            if lead.get("created_at"):
                lead["created_at"] = lead["created_at"].isoformat()
            lead.pop("embedding", None)
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
    valid_statuses = (
        "new", "contacted", "meeting_booked", "qualified", "poc_active",
        "closed_won", "closed_lost", "disqualified", "invalid",
    )
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM leads WHERE id = %s", (lead_id,))
            row = cur.fetchone()
        old_status = (row or {}).get("status", "unknown")
        detail = f"lead {lead_id}: {old_status} -> {status} by {user['email']}"
        log_access(conn, user["email"], "status_change", detail,
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


# ── Single lead (Feature 2) ─────────────────────────────────────────────

@app.get("/api/leads/{lead_id}")
async def api_get_lead(lead_id: int, user=Depends(get_current_user)):
    import json as _json
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
            lead = cur.fetchone()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead = dict(lead)
        if lead.get("created_at"):
            lead["created_at"] = lead["created_at"].isoformat()
        emb = lead.pop("embedding", None)
        try:
            emb_vec = _json.loads(emb) if isinstance(emb, str) else emb
            lead["matched_case_studies"] = match_case_studies(emb_vec) if emb_vec else []
        except Exception:
            lead["matched_case_studies"] = []
        with conn.cursor() as cur:
            cur.execute("SELECT role, linkedin_url FROM contacts WHERE lead_id = %s", (lead_id,))
            contacts = cur.fetchall() or []
        lead["contacts"] = [dict(c) for c in contacts]
        return lead
    finally:
        conn.close()


@app.get("/lead/{lead_id}", response_class=HTMLResponse)
async def lead_page(lead_id: int, user=Depends(get_current_user)):
    return HTMLResponse((static_dir / "index.html").read_text())


# ── Stack analysis (Feature 3) ──────────────────────────────────────────

@app.get("/api/stacks")
async def api_stacks(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tidb_pain FROM leads WHERE tidb_pain IS NOT NULL")
            rows = cur.fetchall() or []
        stack_counts: dict = {}
        pattern = re.compile(r'\[Stack:\s*([^\]]+)\]', re.IGNORECASE)
        for row in rows:
            for m in pattern.finditer(row.get("tidb_pain") or ""):
                s = m.group(1).strip()
                stack_counts[s] = stack_counts.get(s, 0) + 1
        return sorted(
            [{"stack": k, "count": v} for k, v in stack_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )
    finally:
        conn.close()


# ── Admin (Feature 4) ───────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(user=Depends(get_current_user)):
    admin_path = static_dir / "admin.html"
    if not admin_path.exists():
        raise HTTPException(status_code=404, detail="Admin page not found")
    return HTMLResponse(admin_path.read_text())


@app.get("/api/admin/lead-trends")
async def api_admin_lead_trends(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT YEARWEEK(created_at, 1) AS week, COUNT(*) AS count "
                "FROM leads GROUP BY week ORDER BY week DESC LIMIT 12"
            )
            return cur.fetchall() or []
    finally:
        conn.close()


@app.get("/api/admin/score-distribution")
async def api_admin_score_dist(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT fit_score, COUNT(*) AS count FROM leads "
                "GROUP BY fit_score ORDER BY fit_score"
            )
            return cur.fetchall() or []
    finally:
        conn.close()


@app.get("/api/admin/pipeline")
async def api_admin_pipeline_stats(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(status,'new') AS status, COUNT(*) AS count "
                "FROM leads GROUP BY status ORDER BY count DESC"
            )
            return cur.fetchall() or []
    finally:
        conn.close()


@app.get("/api/admin/geo-coverage")
async def api_admin_geo(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT geo, country, COUNT(*) AS leads, "
                "ROUND(AVG(fit_score),1) AS avg_score "
                "FROM leads GROUP BY geo, country ORDER BY leads DESC"
            )
            return cur.fetchall() or []
    finally:
        conn.close()


@app.get("/api/admin/top-industries")
async def api_admin_industries(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT industry, COUNT(*) AS count, ROUND(AVG(fit_score),1) AS avg_score "
                "FROM leads WHERE industry IS NOT NULL "
                "GROUP BY industry ORDER BY count DESC LIMIT 20"
            )
            return cur.fetchall() or []
    finally:
        conn.close()


@app.get("/api/admin/user-activity")
async def api_admin_users(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, COUNT(*) AS events, MAX(created_at) AS last_active, "
                "COUNT(DISTINCT DATE(created_at)) AS active_days "
                "FROM access_log GROUP BY username ORDER BY events DESC"
            )
            rows = cur.fetchall() or []
        for r in rows:
            if r.get("last_active"):
                r["last_active"] = r["last_active"].isoformat()
        return rows
    finally:
        conn.close()


@app.get("/api/admin/recent-leads")
async def api_admin_recent(user=Depends(get_current_user), response: Response = None):
    response.headers["Cache-Control"] = "public, s-maxage=60, stale-while-revalidate=120"
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, company_name, country, industry, fit_score, created_at "
                "FROM leads ORDER BY created_at DESC LIMIT 20"
            )
            rows = cur.fetchall() or []
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return rows
    finally:
        conn.close()


# ── Pre-call brief (Feature 5) ──────────────────────────────────────────

@app.post("/api/leads/{lead_id}/brief")
async def api_generate_brief(
    request: Request, lead_id: int, user=Depends(get_current_user)
):
    import anthropic as _anthropic
    import json as _json
    conn = _db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
            lead = cur.fetchone()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        lead = dict(lead)
        log_access(conn, user["email"], "generate_brief",
                   f"lead {lead_id}: {lead.get('company_name', '')}",
                   getattr(request.client, "host", ""))
    finally:
        conn.close()

    prompt = (
        "You are writing a short, warm outreach email from a Solutions Architect at TiDB Cloud (PingCAP). "
        "This is NOT a sales pitch. This is a genuine offer to share insights.\n\n"
        f"Company: {lead.get('company_name', '')}\n"
        f"Website: {lead.get('website', '')}\n"
        f"Industry: {lead.get('industry', '')}\n"
        f"Country: {lead.get('country', '')}\n"
        f"Pain: {lead.get('tidb_pain', '')}\n"
        f"Outreach Recommendation: {lead.get('outreach_recommendation', '')}\n\n"
        "Write a cold outreach email that follows these rules:\n"
        "1. SUBJECT LINE: Short, specific to their company. No generic subjects. Reference something they actually do.\n"
        "2. OPENING (1 sentence): Acknowledge a specific achievement or strength of their company. Be genuine — reference their product, scale, or market position.\n"
        "3. BRIDGE (1 sentence): Connect their achievement to a challenge you have seen teams like theirs face. Do NOT name the challenge as a problem they have — frame it as a pattern you observe in the industry.\n"
        "4. OFFER (1 sentence): Position a call as offering value — share what you have learned from similar companies, not sell a product. Example: I have been working with teams building [similar thing] and would love to share what we have learned about [relevant topic] — would 20 minutes be useful?\n"
        "5. SIGN-OFF: Sign off as 'Bernard'. No corporate closing.\n\n"
        "Rules:\n"
        "- Address the email to the most likely decision-maker at the company. Use a realistic first name based on the country/region (e.g. 'Hi James,' for English-speaking markets). If unsure, use 'Hi there,'.\n"
        "- NEVER use placeholder brackets like [First Name], [Your Name], [Name], etc. Always use a real name or a generic greeting.\n"
        "- Maximum 5 sentences total. Short paragraphs.\n"
        "- Tone: friendly, peer-to-peer, curious. Like a colleague reaching out, not a vendor.\n"
        "- Do NOT mention TiDB, PingCAP, or any product by name in the email body.\n"
        "- Do NOT use words like: synergy, leverage, optimize, solution, innovative, cutting-edge, pipeline, ROI\n"
        "- Do NOT describe their problems back to them. They know their problems.\n"
        "- Do NOT be technical. No mention of databases, ACID, vectors, tokens, or infrastructure.\n"
        "- The email should make them think: this person understands what we do and might have something useful to share.\n\n"
        "Also generate:\n"
        "- A brief prospect snapshot (2 sentences: who they are, what is impressive about them)\n"
        "- 3 discovery questions to ask on the call (business-focused, not technical)\n\n"
        'Return as JSON:\n'
        '{\n'
        '  "snapshot": "...",\n'
        '  "questions": ["...", "...", "..."],\n'
        '  "email_subject": "...",\n'
        '  "email_body": "..."\n'
        '}'
    )
    client = _anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    content = message.content[0].text
    try:
        json_match = re.search(r'\{[\s\S]*\}', content)
        brief = _json.loads(json_match.group()) if json_match else _json.loads(content)
    except Exception:
        brief = {
            "snapshot": content, "questions": [],
            "email_subject": "", "email_body": "",
        }
    return brief

