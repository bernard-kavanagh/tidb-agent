# TiDB Cloud Lead Generation Agent

AI-powered pipeline that discovers, analyses, and scores companies as potential TiDB Cloud customers — across EMEA, NAMERICA, and APAC.

---

## What it does

1. **Discovers** companies by country using web search (Google/Bing)
2. **Scrapes** their websites for content
3. **Analyses** each company with Claude against three ICP profiles (Database Displacement, AI Compliance, Agentic Workflow Builder)
4. **Scores** fit 1–10 and extracts: pain point, use case, outreach recommendation, HQ country, DB stack
5. **Stores** leads in TiDB Cloud with deduplication and HQ-country correction
6. **Serves** a FastAPI dashboard with search, filtering, semantic search, and case study matching

---

## Project structure

```
tidb_agent/
├── agent/
│   ├── config.py          # Env vars, geo/region/country maps, compliance contexts
│   ├── run.py             # Main orchestrator — CLI entry point
│   ├── discovery.py       # Web search → company list
│   ├── scraper.py         # Website content fetcher
│   ├── analyzer.py        # Claude ICP analysis + scoring
│   ├── storage.py         # TiDB upsert / query helpers
│   ├── embeddings.py      # Sentence-transformer embeddings + hybrid search
│   ├── case_matcher.py    # Cosine similarity case study matcher
│   └── case_studies.py    # TiDB reference customers with URLs
├── dashboard/
│   ├── main.py            # FastAPI app
│   └── static/index.html  # Single-page dashboard UI
├── pitch_scripts/         # Regional pitch & demo scripts (EMEA / NAMERICA / APAC)
├── schema.sql             # TiDB table definitions + migration comments
├── embed_leads.py         # One-off: generate embeddings for existing leads
├── requirements.txt
└── .env                   # Not committed — see setup below
```

---

## Setup

```bash
cd ~/tidb_agent
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:
```
ANTHROPIC_API_KEY=sk-ant-...
TIDB_CONNECTION_STRING=mysql+pymysql://user:pass@host:4000/tidb_leads?ssl_ca=...
DASHBOARD_USER=tidb
DASHBOARD_PASS=your_password
```

Apply schema (first time or after migrations):
```bash
mysql -h HOST -P 4000 -u USER -p tidb_leads < schema.sql
```

---

## Running the agent

```bash
# Activate venv first
source venv/bin/activate

# All EMEA countries (default)
python -m agent.run

# Specific geo
python -m agent.run --geo NAMERICA
python -m agent.run --geo APAC
python -m agent.run --geo ALL

# Sub-region or specific countries
python -m agent.run --region "Northern Europe"
python -m agent.run --countries "Japan,India"

# Minimum fit score filter (default: 5)
python -m agent.run --geo NAMERICA --min-score 7
```

---

## Running the dashboard

```bash
source venv/bin/activate
uvicorn dashboard.main:app --reload --port 8000
```

Open `http://localhost:8000`. Login with `DASHBOARD_USER` / `DASHBOARD_PASS`.

---

## Utility scripts

**Backfill outreach recommendations** (for leads missing `outreach_recommendation`):
```bash
cd ~/tidb_agent
python3 ~/backfill_outreach.py --project tidb --dry-run
python3 ~/backfill_outreach.py --project tidb --limit 100
```

**Backfill / fix HQ countries** (verifies country assignments, deduplicates):
```bash
cd ~/tidb_agent
python3 ~/backfill_hq.py --project tidb --dry-run
python3 ~/backfill_hq.py --project tidb --limit 100
```

**Generate embeddings** for existing leads:
```bash
python3 embed_leads.py
```

---

## ICP profiles

| Profile | Who | db signal |
|---|---|---|
| Database Displacement | MySQL/Aurora/DynamoDB shops adding vector search | Managing 2+ systems (SQL + Pinecone/OpenSearch) |
| AI Compliance | Healthcare/Finance/HR/Legal AI | Regulated sector + agentic decision-making |
| Agentic Workflow Builder | Multi-step agent pipelines, copilots | Postgres + vector DB split, MCP-native |

**Scoring**: 9-10 = perfect ICP match, 7-8 = strong, 5-6 = moderate, 3-4 = weak, 1-2 = poor.

---

## Models

- `claude-haiku-4-5-20251001` — default (fast, cheap; used for analysis and backfills)
- `claude-sonnet-4-6` — stored as `CLAUDE_MODEL_STRONG` for future high-quality tasks
- `all-MiniLM-L6-v2` (sentence-transformers) — 384-dim embeddings for semantic lead search
