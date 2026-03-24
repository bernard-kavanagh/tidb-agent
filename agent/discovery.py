"""
Company discovery: finds AI/tech companies in each EMEA country.

Strategy:
1. Scrape curated startup/tech directories per country (eu-startups.com, f6s.com, etc.)
2. Ask Claude to augment with known AI companies per country (when scraping yields few results)
"""
import json
from urllib.parse import quote_plus

import anthropic

from .config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_COMPANIES_PER_COUNTRY, COUNTRY_MAX_OVERRIDE, GEO_COMPLIANCE
from .scraper import extract_company_cards, scrape_text

# ---------------------------------------------------------------------------
# Directory sources per country
# Each entry: (directory_url, label)
# We extract company cards from these pages.
# ---------------------------------------------------------------------------
DIRECTORY_SOURCES: dict[str, list[str]] = {
    # Western Europe
    "United Kingdom": [
        "https://www.f6s.com/companies/artificial-intelligence/gb/co",
        "https://eu-startups.com/directory/?country=United+Kingdom&category=Artificial+Intelligence",
    ],
    "Ireland": [
        "https://www.f6s.com/companies/artificial-intelligence/ie/co",
        "https://eu-startups.com/directory/?country=Ireland&category=Artificial+Intelligence",
    ],
    "France": [
        "https://www.f6s.com/companies/artificial-intelligence/fr/co",
        "https://eu-startups.com/directory/?country=France&category=Artificial+Intelligence",
    ],
    "Germany": [
        "https://www.f6s.com/companies/artificial-intelligence/de/co",
        "https://eu-startups.com/directory/?country=Germany&category=Artificial+Intelligence",
    ],
    "Netherlands": [
        "https://www.f6s.com/companies/artificial-intelligence/nl/co",
        "https://eu-startups.com/directory/?country=Netherlands&category=Artificial+Intelligence",
    ],
    "Belgium": [
        "https://www.f6s.com/companies/artificial-intelligence/be/co",
    ],
    "Switzerland": [
        "https://www.f6s.com/companies/artificial-intelligence/ch/co",
    ],
    "Austria": [
        "https://www.f6s.com/companies/artificial-intelligence/at/co",
    ],
    "Luxembourg": [
        "https://www.f6s.com/companies/artificial-intelligence/lu/co",
    ],
    # Northern Europe
    "Sweden": [
        "https://www.f6s.com/companies/artificial-intelligence/se/co",
        "https://eu-startups.com/directory/?country=Sweden&category=Artificial+Intelligence",
    ],
    "Norway": [
        "https://www.f6s.com/companies/artificial-intelligence/no/co",
    ],
    "Denmark": [
        "https://www.f6s.com/companies/artificial-intelligence/dk/co",
    ],
    "Finland": [
        "https://www.f6s.com/companies/artificial-intelligence/fi/co",
    ],
    "Iceland": [
        "https://www.f6s.com/companies/artificial-intelligence/is/co",
    ],
    "Estonia": [
        "https://www.f6s.com/companies/artificial-intelligence/ee/co",
    ],
    "Latvia": [
        "https://www.f6s.com/companies/artificial-intelligence/lv/co",
    ],
    "Lithuania": [
        "https://www.f6s.com/companies/artificial-intelligence/lt/co",
    ],
    # Southern Europe
    "Spain": [
        "https://www.f6s.com/companies/artificial-intelligence/es/co",
        "https://eu-startups.com/directory/?country=Spain&category=Artificial+Intelligence",
    ],
    "Portugal": [
        "https://www.f6s.com/companies/artificial-intelligence/pt/co",
    ],
    "Italy": [
        "https://www.f6s.com/companies/artificial-intelligence/it/co",
        "https://eu-startups.com/directory/?country=Italy&category=Artificial+Intelligence",
    ],
    "Greece": [
        "https://www.f6s.com/companies/artificial-intelligence/gr/co",
    ],
    "Malta": [],
    "Cyprus": [],
    # Eastern Europe
    "Poland": [
        "https://www.f6s.com/companies/artificial-intelligence/pl/co",
        "https://eu-startups.com/directory/?country=Poland&category=Artificial+Intelligence",
    ],
    "Czech Republic": [
        "https://www.f6s.com/companies/artificial-intelligence/cz/co",
    ],
    "Hungary": [
        "https://www.f6s.com/companies/artificial-intelligence/hu/co",
    ],
    "Romania": [
        "https://www.f6s.com/companies/artificial-intelligence/ro/co",
    ],
    "Slovakia": [],
    "Bulgaria": [],
    "Croatia": [],
    "Slovenia": [],
    # Middle East
    "Israel": [
        "https://www.f6s.com/companies/artificial-intelligence/il/co",
        "https://www.start-up.co.il/en",
    ],
    "United Arab Emirates": [
        "https://www.f6s.com/companies/artificial-intelligence/ae/co",
        "https://www.magnitt.com/startups/artificial-intelligence",
    ],
    "Saudi Arabia": [
        "https://www.f6s.com/companies/artificial-intelligence/sa/co",
    ],
    "Qatar": [],
    "Bahrain": [],
    "Kuwait": [],
    "Jordan": [],
    "Lebanon": [],
    # Africa
    "South Africa": [
        "https://www.f6s.com/companies/artificial-intelligence/za/co",
    ],
    "Nigeria": [
        "https://www.f6s.com/companies/artificial-intelligence/ng/co",
    ],
    "Kenya": [
        "https://www.f6s.com/companies/artificial-intelligence/ke/co",
    ],
    "Ghana": [],
    "Egypt": [
        "https://www.f6s.com/companies/artificial-intelligence/eg/co",
    ],
    "Morocco": [],
    "Tunisia": [],
    # ---------------------------------------------------------------------------
    # NAMERICA
    # ---------------------------------------------------------------------------
    "United States": [
        "https://www.f6s.com/companies/artificial-intelligence/us/co",
        "https://builtin.com/companies/type/artificial-intelligence-companies",
    ],
    "Canada": [
        "https://www.f6s.com/companies/artificial-intelligence/ca/co",
    ],
    "Mexico": [
        "https://www.f6s.com/companies/artificial-intelligence/mx/co",
    ],
    "Brazil": [
        "https://www.f6s.com/companies/artificial-intelligence/br/co",
    ],
    "Colombia": [
        "https://www.f6s.com/companies/artificial-intelligence/co/co",
    ],
    "Argentina": [
        "https://www.f6s.com/companies/artificial-intelligence/ar/co",
    ],
    "Chile": [
        "https://www.f6s.com/companies/artificial-intelligence/cl/co",
    ],
    # ---------------------------------------------------------------------------
    # APAC
    # ---------------------------------------------------------------------------
    "Japan": [
        "https://www.f6s.com/companies/artificial-intelligence/jp/co",
    ],
    "South Korea": [
        "https://www.f6s.com/companies/artificial-intelligence/kr/co",
    ],
    "Taiwan": [
        "https://www.f6s.com/companies/artificial-intelligence/tw/co",
    ],
    "Hong Kong": [
        "https://www.f6s.com/companies/artificial-intelligence/hk/co",
    ],
    "Singapore": [
        "https://www.f6s.com/companies/artificial-intelligence/sg/co",
    ],
    "Vietnam": [
        "https://www.f6s.com/companies/artificial-intelligence/vn/co",
    ],
    "Thailand": [
        "https://www.f6s.com/companies/artificial-intelligence/th/co",
    ],
    "Indonesia": [
        "https://www.f6s.com/companies/artificial-intelligence/id/co",
    ],
    "Malaysia": [
        "https://www.f6s.com/companies/artificial-intelligence/my/co",
    ],
    "Philippines": [
        "https://www.f6s.com/companies/artificial-intelligence/ph/co",
    ],
    "India": [
        "https://www.f6s.com/companies/artificial-intelligence/in/co",
    ],
    "Australia": [
        "https://www.f6s.com/companies/artificial-intelligence/au/co",
    ],
    "New Zealand": [
        "https://www.f6s.com/companies/artificial-intelligence/nz/co",
    ],
}


def _dedupe(companies: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for c in companies:
        key = c.get("website", "").lower().rstrip("/")
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _claude_seed(client: anthropic.Anthropic, country: str, n: int = 15, geo: str = "EMEA") -> list[dict]:
    """
    Ask Claude to generate a seed list of AI/tech companies in a country
    that fit TiDB Cloud's three core ICP lenses.
    """
    compliance_context = GEO_COMPLIANCE.get(geo.upper(), GEO_COMPLIANCE["EMEA"])
    namerica_extra = """
━━ NAMERICA-SPECIFIC TARGETING ━━
For North America, prioritise these additional high-value profiles:
- AWS-HEAVY companies currently on Amazon Aurora, DynamoDB, or RDS MySQL who are adding AI
  features and facing the two-database problem (Aurora + Pinecone, DynamoDB + OpenSearch)
- Y COMBINATOR / VC-BACKED AI startups scaling fast — serverless branching is the "git for
  prod databases" story that resonates with rapid-iteration engineering culture
- HEALTHCARE AI companies (clinical decision support, medical imaging, patient data platforms)
  — HIPAA audit trail requirements make TiDB's ACID log + Right to Deletion compelling
- FINTECH AI (credit scoring, fraud detection, algorithmic trading) — SOC2 + real-time analytics
  on the same dataset is a direct Aurora/DynamoDB limitation
- ENTERPRISE SAAS companies scaling to thousands of tenants who need per-tenant isolation
  (TiDB serverless branching = instant per-customer database clone)
Do NOT limit to pure AI companies — include any tech company with a clear AI infrastructure need.
""" if geo.upper() == "NAMERICA" else ""

    prompt = f"""List {n} real AI or tech companies and startups based in {country} that are strong candidates for TiDB Cloud — the first database purpose-built for the era where AI agents are the primary users.

Applicable compliance framework for this region ({geo}): {compliance_context}
{namerica_extra}

The framing: the database was the system of record. In the agent era, it becomes the system of thought.
TiDB Cloud is a unified, MySQL-compatible distributed database with HTAP, native vector search, serverless
branching, and a native MCP Server that lets AI agents query the full data substrate in natural language.

Target companies across FIVE distinct profiles. Aim for a balanced mix:

━━ PROFILE 1 — DATABASE DISPLACEMENT CANDIDATES ━━
Companies currently on MySQL, Amazon Aurora, Microsoft SQL Server, Google Spanner, or DynamoDB
who are hitting hard limits because of AI workloads — specifically:
- MySQL/Aurora users adding vector search and facing the "two-database problem" (Postgres + Pinecone, Aurora + OpenSearch)
- DynamoDB or Spanner shops that need relational joins + vector search together but are fighting NoSQL constraints
- MSSQL users scaling out of on-premise into cloud-native AI and needing MySQL-compatible migration
- Any company whose AI features require stitching SQL + vector + analytics across 2+ separate systems

━━ PROFILE 2 — EU AI ACT COMPLIANCE TARGETS ━━
Companies building AI systems that fall under HIGH-RISK categories in the EU AI Act —
these companies legally need: full auditability of AI decisions, traceability of agent actions,
human oversight checkpoints, data lineage, and Right to be Forgotten.
Target sectors: Healthcare AI (clinical decision support, diagnostics), Financial AI (credit scoring,
fraud detection, trading), HR/Recruitment AI (CV screening, hiring), Legal AI (contract analysis,
court-facing tools), Government/Public Services AI, Critical Infrastructure AI.
TiDB is uniquely suited: ACID audit logs, serverless branching for human-in-the-loop approval,
and Right to be Forgotten as a single SQL command across all data types.

━━ PROFILE 3 — AGENTIC WORKFLOW BUILDERS ━━
Companies building actual agent pipelines — not just AI products, but systems where:
- Agents take multi-step autonomous actions and need persistent memory across sessions
- Multi-agent platforms coordinate specialised sub-agents with shared state
- Copilots write/read/update structured data as part of their reasoning loop
- Agent orchestration platforms (workflow automation, research agents, coding agents, customer agents)
- AI-native applications where the database IS the agent's system of thought, not just storage
These companies will hit the Memory Wall (separate SQL + vector + analytics) within 6-12 months
of scaling, making them urgent TiDB prospects.

━━ PROFILE 4 — EPISODIC MEMORY BUILDERS ━━
Companies whose AI agents need to LEARN over time by writing experiences back as vector embeddings —
the Decide-Validate-Remember loop. This means:
- Agents that record what they did, what happened, and what worked — stored as both structured data and vectors
- Systems where "agent memory" is a first-class product feature, not an afterthought
- Companies building AI that gets smarter with each interaction by recalling past decisions
- Reference profile: Manus (runs 10M+ ephemeral TiDB databases per agent swarm). Look for companies
  building at similar scale or with similar architecture — many short-lived isolated agent contexts.
TiDB is the only database that unifies structured state + vector episodic memory in one ACID engine.

━━ PROFILE 5 — MCP-NATIVE COMPANIES ━━
Companies actively building with AI agent frameworks that use the Model Context Protocol (MCP) or
similar tool-use patterns — Claude, LangChain, LlamaIndex, CrewAI, AutoGen, Cursor, etc.
TiDB's native MCP Server lets agents query the full data substrate in natural language — no middleware,
no custom connectors. These companies are an immediate integration fit.
Look for: companies whose job postings mention MCP, tool-use, Claude API, LangChain integrations,
or whose products explicitly support AI agent tool calling.

Include well-known companies AND lesser-known startups — do not only list the most famous.
For each, provide their real website URL.

Return ONLY a JSON array, no other text:
[
  {{"name": "Company Name", "website": "https://example.com"}},
  ...
]"""

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        raw = msg.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        return []


def discover_companies(
    country: str,
    client: anthropic.Anthropic,
    min_results: int = 10,
    geo: str = "EMEA",
) -> list[dict]:
    """
    Discover AI companies in a given country.
    Returns list of {"name": str, "website": str}.
    """
    country_max = COUNTRY_MAX_OVERRIDE.get(country, MAX_COMPANIES_PER_COUNTRY)
    companies: list[dict] = []

    # Phase 1: scrape directories
    sources = DIRECTORY_SOURCES.get(country, [])
    for url in sources:
        cards = extract_company_cards(url)
        companies.extend(cards)

    companies = _dedupe(companies)

    # Phase 2: always supplement with Claude seed list for better ICP targeting
    seed_n = max(min_results, 30)
    if len(companies) < max(min_results, 20):
        seed = _claude_seed(client, country, n=seed_n, geo=geo)
        companies.extend(seed)
        companies = _dedupe(companies)

    # Apply cap only if set (0 = unlimited)
    if country_max > 0:
        return companies[:country_max]
    return companies
