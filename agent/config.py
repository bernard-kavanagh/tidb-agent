import os
from dotenv import load_dotenv

# Always resolve .env relative to this file so it loads regardless of CWD
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'), override=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TIDB_CONNECTION_STRING = os.getenv("TIDB_CONNECTION_STRING", "")

SCRAPER_DELAY = float(os.getenv("SCRAPER_DELAY", "1.5"))
MAX_COMPANIES_PER_COUNTRY = int(os.getenv("MAX_COMPANIES_PER_COUNTRY", "0"))  # 0 = unlimited
MIN_FIT_SCORE = int(os.getenv("MIN_FIT_SCORE", "5"))

# No per-country caps — discover and analyse everything we find
COUNTRY_MAX_OVERRIDE: dict[str, int] = {}

CLAUDE_MODEL        = "claude-haiku-4-5-20251001"
CLAUDE_MODEL_STRONG = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Full geo → sub-region → country hierarchy
# ---------------------------------------------------------------------------
GEO_REGIONS: dict[str, dict[str, list[str]]] = {
    "EMEA": {
        "Western Europe": [
            "United Kingdom", "Ireland", "France", "Germany",
            "Netherlands", "Belgium", "Luxembourg", "Switzerland", "Austria",
        ],
        "Northern Europe": [
            "Sweden", "Norway", "Denmark", "Finland", "Iceland",
            "Estonia", "Latvia", "Lithuania",
        ],
        "Southern Europe": [
            "Spain", "Portugal", "Italy", "Greece", "Malta", "Cyprus",
        ],
        "Eastern Europe": [
            "Poland", "Czech Republic", "Hungary", "Romania", "Slovakia",
            "Bulgaria", "Croatia", "Slovenia",
        ],
        "Middle East": [
            "Israel", "United Arab Emirates", "Saudi Arabia", "Qatar",
            "Bahrain", "Kuwait", "Jordan", "Lebanon",
        ],
        "Africa": [
            "South Africa", "Nigeria", "Kenya", "Ghana", "Egypt",
            "Morocco", "Tunisia",
        ],
    },
    "NAMERICA": {
        "North America": [
            "United States", "Canada",
        ],
        "Latin America": [
            "Mexico", "Brazil", "Colombia", "Argentina", "Chile",
        ],
    },
    "APAC": {
        "East Asia": [
            "Japan", "South Korea", "Taiwan", "Hong Kong",
        ],
        "Southeast Asia": [
            "Singapore", "Vietnam", "Thailand", "Indonesia", "Malaysia", "Philippines",
        ],
        "South Asia": [
            "India",
        ],
        "ANZ": [
            "Australia", "New Zealand",
        ],
    },
}

# Compliance framework per geo — used by analyzer to tailor the scoring prompt
GEO_COMPLIANCE: dict[str, str] = {
    "EMEA": (
        "EU AI Act (mandatory for high-risk AI sectors: healthcare, finance, HR, legal, government, "
        "critical infrastructure). Key requirements: full auditability of AI decisions, traceability "
        "of agent actions, human oversight checkpoints, data lineage, Right to be Forgotten. "
        "Also: GDPR data residency, cross-border transfer restrictions."
    ),
    "NAMERICA": (
        "US/Canada compliance: HIPAA (healthcare AI — patient data audit trail), CCPA/CPRA (California "
        "consumer data rights, Right to Deletion), SOC 2 Type II (enterprise SaaS), FTC Act (unfair AI "
        "practices), SEC AI disclosure rules (financial AI), PIPEDA (Canada). No single federal AI Act "
        "yet but sector-specific rules are strict — especially healthcare and finance."
    ),
    "APAC": (
        "APAC compliance varies by country: Singapore PDPA + Model AI Governance Framework; "
        "India DPDP Act 2023 (Right to Erasure, consent); Australia Privacy Act + APPs (AI transparency); "
        "Japan APPI amendments (sensitive data, cross-border transfers); South Korea PIPA; "
        "Taiwan PDPA; Hong Kong PDPO. China PIPL + Generative AI Regulations (algorithmic "
        "transparency, training data provenance, mandatory security assessments for high-risk AI). "
        "Companies operating across APAC face a patchwork of overlapping data localisation rules."
    ),
}

# ---------------------------------------------------------------------------
# Flat lookups derived from GEO_REGIONS
# ---------------------------------------------------------------------------

# country -> sub-region (e.g. "Sweden" -> "Northern Europe")
COUNTRY_REGION: dict[str, str] = {
    country: sub_region
    for geo, sub_regions in GEO_REGIONS.items()
    for sub_region, countries in sub_regions.items()
    for country in countries
}

# country -> geo (e.g. "Sweden" -> "EMEA")
COUNTRY_GEO: dict[str, str] = {
    country: geo
    for geo, sub_regions in GEO_REGIONS.items()
    for sub_region, countries in sub_regions.items()
    for country in countries
}

# Legacy: flat EMEA sub-region map (kept for backwards compat with --region flag)
EMEA_REGIONS: dict[str, list[str]] = GEO_REGIONS["EMEA"]


def all_countries(geo: str | None = None) -> list[str]:
    """Return all countries for a given geo, or all geos if geo is None."""
    if geo:
        return [
            country
            for sub_regions in GEO_REGIONS.get(geo.upper(), {}).values()
            for country in sub_regions
        ]
    return [
        country
        for sub_regions_map in GEO_REGIONS.values()
        for sub_regions in sub_regions_map.values()
        for country in sub_regions
    ]
