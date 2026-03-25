"""
Claude-powered company analysis.
Takes raw website text and returns structured lead intelligence.
"""
import json
import re

import anthropic

from .config import CLAUDE_MODEL, GEO_COMPLIANCE

SYSTEM_PROMPT = """You are a senior sales analyst for TiDB Cloud — PingCAP's unified, MySQL-compatible distributed database platform built for AI-era applications.

The primary users of databases are becoming AI agents. Not in five years. Now. TiDB Cloud is the first
database purpose-built for the era where AI agents are the primary users — not a database with AI
features bolted on, but the foundational substrate of the agent era. The database was the system of
record. In the agent era, it becomes the system of thought.

TiDB Cloud core capabilities:
- HTAP architecture: handles OLTP and real-time analytics on the same live data (no ETL, no separate data warehouse)
- Native Vector Search: up to 16,383 dimensions with HNSW indexes — semantic/hybrid search built in, no Pinecone needed
- Serverless branching: copy-on-write database snapshots for safe agent experimentation (Git-for-databases)
- Unified substrate: structured data + vector embeddings + analytical queries in one ACID-compliant engine
- MySQL-compatible: zero application rewrite for teams already on MySQL, Aurora, or MSSQL
- Auto-scaling serverless: 80% TCO reduction vs always-on instances; only pay for active compute seconds
- Enterprise-grade: ACID-compliant, full transaction audit log, GDPR/CCPA/SOC2, multi-region
- Online DDL: agents can evolve schemas without downtime — no manual migration windows
- Native MCP Server: AI agents query TiDB via natural language / MCP protocol — no middleware, no custom connectors
- Episodic Memory: agents write experiences (actions + outcomes) back as vector embeddings — TiDB becomes a learning system, not just a data store

TiDB Cloud's economic value — beyond the Token Tax:
AI agents pay a 'Token Tax' every time they re-read their own history. Any database can checkpoint
state to reduce this tax. But TiDB Cloud goes further — the checkpoint data becomes learning data:
- Token Tax elimination: agents checkpoint state to TiDB instead of carrying full history in context. Same 80-90% token cost reduction as any stateful approach.
- But TiDB's unique edge: the checkpoint isn't disposable. Agent decisions and outcomes are written back as vector embeddings (Episodic Memory), so the system LEARNS from every task. The Decide-Validate-Remember loop turns operational cost into compound intelligence.
- Unified economics: structured state + vector embeddings + real-time analytics in one engine means no ETL tax, no sync tax, no multi-system operational tax on top of the Token Tax savings.
- The pitch: 'Other databases save you the Token Tax. TiDB eliminates it AND makes your agents smarter with every task.'

TiDB Cloud's ICP has THREE distinct buying profiles. Score against all three:

━━ PROFILE 1 — DATABASE DISPLACEMENT ━━
Companies on MySQL, Amazon Aurora, Microsoft SQL Server, Google Spanner, or DynamoDB
who are now hitting AI-related limits:
- MySQL/Aurora shops adding vector search, now managing a second database (Pinecone, pgvector, OpenSearch)
- DynamoDB users who need relational joins + vector search but are fighting NoSQL constraints
- Spanner users locked into GCP proprietary APIs who want cloud-agnostic MySQL compatibility
- MSSQL shops migrating to cloud-native AI and needing a MySQL-compatible drop-in
- Any team stitching SQL + vector + analytics across 2+ systems — the "Memory Wall"

━━ PROFILE 2 — AI COMPLIANCE ━━
Companies operating in REGULATED SECTORS where AI decisions must be auditable — regardless
of whether they explicitly advertise compliance on their website. Detect by sector and product
type, not by the presence of compliance keywords.
The applicable framework depends on geography — see the geo context in this prompt.
High-risk sectors across all geos: Healthcare AI (clinical decision support, diagnostics,
patient data, medical imaging, drug discovery), Financial AI (credit scoring, fraud detection,
trading, lending, insurance), HR/Recruitment AI (CV screening, hiring decisions), Legal AI
(contract analysis, court-facing tools), Government/Public Services AI, Critical Infrastructure.
NAMERICA-specific signals: any healthcare AI handling PHI = HIPAA; any US fintech = SOC2 + CCPA;
any platform storing personal data of California residents = CCPA Right to Deletion.
APAC-specific signals: any company with Singapore/India/Australia data = PDPA/DPDP/APPs.
TiDB's compliance value: ACID transaction log = provable audit trail for every agent decision;
serverless branching = human-in-the-loop approval gate before AI changes reach production;
Right to be Forgotten / Right to Erasure = single SQL command across structured + vector data.

━━ PROFILE 3 — AGENTIC WORKFLOW BUILDERS ━━
Companies building actual agent pipelines — not just AI products, but systems where:
- Agents take multi-step autonomous actions and need persistent memory across sessions
- Multi-agent platforms coordinate specialised sub-agents with shared structured + vector state
- Copilots write/read/update structured data as part of their active reasoning loop
- Agent orchestration platforms (workflow automation, research agents, coding agents, customer service agents)
- AI-native SaaS where the database IS the agent's cognitive architecture — the "system of thought"
- EPISODIC MEMORY BUILDERS: agents that write their experiences (decisions + outcomes) back as vector
  embeddings so the system learns over time — the Decide-Validate-Remember loop. Manus is the reference
  customer: 10M+ ephemeral databases created by AI agents, needing a substrate that scales from zero to
  millions of isolated contexts in milliseconds.
- MCP-NATIVE COMPANIES: teams building with Claude, LangChain, or similar frameworks using MCP tool-use
  patterns — TiDB's native MCP Server lets agents query the full data substrate in natural language,
  making these companies an immediate integration fit.
These are the most urgent TiDB leads — they will hit the Memory Wall within 6-12 months of scaling,
facing fragmented Postgres + vector DB + S3 stacks and paying the "Agentic Tax" in engineering overhead.

Your job: analyse a company, identify which ICP profile(s) apply, and score fit precisely."""

ANALYSIS_PROMPT = """Analyse this company as a potential TiDB Cloud customer across three ICP lenses.

Company: {company_name}
Website: {website}
Geography: {geo}
Applicable compliance framework: {compliance_context}

Website content:
---
{content}
---

Return ONLY valid JSON (no markdown, no explanation):
{{
  "description": "2-3 sentence description of what the company does and their main product",
  "icp_profile": "Which of the three profiles applies — one or more of: 'Database Displacement', 'EU AI Act Compliance', 'Agentic Workflow Builder', 'Episodic Memory Builder', 'MCP-Native'. Comma-separate if multiple apply.",
  "db_stack": "Inferred or detected current database technology (e.g. 'MySQL + Pinecone', 'Aurora + OpenSearch', 'DynamoDB', 'MSSQL', 'Spanner', 'Postgres + pgvector', 'Unknown'). Look for clues in job postings, tech stack mentions, integrations listed on the site.",
  "tidb_pain": "Specific pain point this company has that TiDB Cloud solves — be concrete and reference the correct ICP profile. Examples: DB Displacement: 'Running Aurora + Pinecone for their AI agents — paying the Memory Wall tax across two systems with ETL lag and sync complexity'; EU AI Act: 'Builds clinical decision-support AI under EU AI Act high-risk category — needs ACID audit trail for every agent decision and Right to be Forgotten across structured + vector data'; Agentic: 'Building a multi-agent research platform where each agent needs persistent memory; their current Postgres + vector DB split means stale context and hallucinations at scale'; Episodic Memory: 'Agents need to write decisions and outcomes back as vector embeddings so the system learns — requires a unified store for structured state and vector memory in one ACID engine'; MCP-Native: 'Building with Claude/LangChain tool-use patterns — TiDB native MCP Server lets agents query the full data substrate in natural language with no middleware'. Also assess the Token Tax exposure: does this company run multi-step agent workflows where context windows grow? Do they connect agents to multiple data sources? If so, position TiDB as both the Token Tax solution AND the episodic memory layer — checkpointing that compounds into intelligence.",
  "tidb_use_case": "One concrete use case: how would they specifically use TiDB Cloud? Reference their actual product. E.g. 'Migrate their Aurora + Pinecone stack to TiDB Cloud Serverless — unified HTAP cluster stores agent session memory, product embeddings, and real-time usage analytics in one engine; serverless branching gives their DBA agent a safe sandbox for schema changes before prod merge; agent writes fix outcomes back as vector embeddings for episodic recall — the Decide-Validate-Remember loop closes in a single substrate'",
  "fit_score": <integer 1-10, where 10 = perfect ICP match>,
  "industry": "Industry category (e.g. 'AI Infrastructure', 'Healthcare AI', 'Legal AI', 'HR Tech', 'Fintech', 'Enterprise SaaS', 'Developer Tools', 'Agent Orchestration', 'E-commerce', etc.)",
  "company_size": "Estimated headcount band: '1-10', '11-50', '51-200', '201-500', '501-1000', or '1000+'. Use 'Unknown' if unclear.",
  "icp_contacts": ["Pick 3-5 from these GTM-aligned titles based on company profile — CTO, VP Engineering, Head of Data & AI, AI/ML Platform Lead, Chief Compliance Officer, Head of Backend Engineering, VP Product, Principal Engineer, Head of AI Infrastructure, Data Engineer Lead"],
  "outreach_recommendation": "1-2 sentence actionable outreach angle. Lead with the specific TiDB value prop — name the MySQL/Aurora sharding pain, the real-time analytics gap, or the AI agent memory pattern. Be concrete and reference their actual stack. When the company runs multi-step agent workflows, lead with the Token Tax angle first (immediate cost savings they can calculate), then pivot to episodic memory (long-term compound intelligence). The Token Tax opens the door, episodic memory closes the deal.",
  "hq_country": "The company headquarters country based on website content, about page, contact info, or any other signals. If the website clearly shows HQ is in a different country than the discovery country ({country}), return the CORRECT country. If unclear, return the discovery country."
}}

Scoring guide — award the highest applicable score:

9-10 PERFECT FIT (any one of):
  • Episodic Memory Builder: agents write decisions + outcomes back as vector embeddings — needs the Decide-Validate-Remember loop in a single ACID engine (Manus-profile company)
  • Agentic Workflow Builder actively hitting the Memory Wall (Postgres + vector DB + S3 or equivalent fragmented stack, multi-agent platform, autonomous agent with persistent memory)
  • Multi-step agent orchestration where context windows grow quadratically — massive Token Tax exposure that TiDB checkpointing directly solves, PLUS episodic memory potential where checkpoint data becomes vector embeddings for agent learning
  • EU AI Act HIGH-RISK sector (healthcare/finance/HR/legal AI) with agentic or autonomous decision-making AND scale
  • Database Displacement: on Aurora/MySQL/DynamoDB/Spanner AND already using a second system for vectors or analytics — immediate migration candidate
  • MCP-Native: building with Claude/LangChain tool-use and needs a unified data substrate the agent can query directly

7-8 STRONG FIT (any one of):
  • Building AI agents or copilots but not yet at Memory Wall scale — will hit it within 12 months
  • AI features with growing context requirements (long conversations, document processing, multi-tool workflows) — moderate Token Tax exposure that TiDB checkpointing can address
  • EU AI Act exposure in a regulated sector (healthcare, finance, legal) even without explicit agent architecture
  • MySQL/Aurora/MSSQL shop with clear AI roadmap and growing data complexity
  • Multi-tenant SaaS platform needing per-tenant database isolation at scale (thousands of ephemeral contexts)
  • AI-native product where the database functions as the system of thought, not just storage

5-6 MODERATE FIT:
  • Data-heavy tech company with AI on the roadmap but not yet building agents
  • Using a modern database but with architectural signals (separate warehouse, vector addon) suggesting future fragmentation
  • Compliance-aware company in a regulated sector not yet building AI agents

3-4 WEAK FIT:
  • Traditional tech company, limited data complexity, no AI signals
  • Non-technical B2C product with no visible data infrastructure needs

1-2 POOR FIT:
  • Non-technical company, pure services business, or no data infrastructure whatsoever

ICP contacts: 3-5 titles from this GTM-aligned list based on the company's profile:
  Agentic/Technical leads: CTO, VP Engineering, Head of Data & AI, AI/ML Platform Lead, Principal Engineer, Head of AI Infrastructure, Data Engineer Lead
  Compliance leads (EU AI Act profile): Chief Compliance Officer, Head of Legal & Compliance, Chief Risk Officer, DPO
  Product leads: VP Product, Head of AI Products
  Always include Head of Data & AI or AI/ML Platform Lead for any Agentic or Episodic Memory profile."""


def analyse_company(
    client: anthropic.Anthropic,
    company_name: str,
    website: str,
    content: str | None,
    geo: str = "EMEA",
    country: str = "",
) -> dict | None:
    """
    Returns structured analysis dict or None on failure.
    """
    if not content:
        content = "(No website content available — use company name and domain to infer)"

    compliance_context = GEO_COMPLIANCE.get(geo.upper(), GEO_COMPLIANCE["EMEA"])
    prompt = ANALYSIS_PROMPT.format(
        company_name=company_name,
        website=website,
        geo=geo.upper(),
        compliance_context=compliance_context,
        content=content[:5000],
        country=country or "Unknown",
    )

    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1536,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()

        # Strip markdown code fences if Claude wraps in them
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        result = json.loads(raw)

        # Validate required fields
        required = {"description", "tidb_pain", "tidb_use_case", "fit_score", "industry", "company_size", "icp_contacts", "outreach_recommendation", "hq_country"}
        if not required.issubset(result.keys()):
            return None

        # Normalise optional new fields — store in tidb_pain if present
        icp_profile = result.pop("icp_profile", "")
        db_stack    = result.pop("db_stack", "")
        if icp_profile or db_stack:
            prefix = []
            if icp_profile: prefix.append(f"[{icp_profile}]")
            if db_stack and db_stack.lower() not in ("unknown", ""):
                prefix.append(f"[Stack: {db_stack}]")
            if prefix:
                result["tidb_pain"] = " ".join(prefix) + " " + result["tidb_pain"]

        result["fit_score"] = max(1, min(10, int(result["fit_score"])))
        return result

    except Exception:
        return None
