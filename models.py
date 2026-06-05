"""
Data classes for the CTR Optimization Tool.
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional, List


@dataclass
class ClientRecord:
    """One active client / Ahrefs project."""
    project_name: str   # Raw Ahrefs project name
    client_name: str    # Clean name after alias mapping
    domain: str         # Bare domain (e.g. "example.com")
    strategist: str = "Unassigned"
    is_red_flag: bool = False


@dataclass
class CompetitorResult:
    """Title/meta from one SERP position for a query."""
    position: int
    title: str
    meta: str
    url: str


@dataclass
class PageOpportunity:
    """One page with underperforming CTR, plus enrichment data."""

    # Identity
    client_name: str
    domain: str
    strategist: str
    is_red_flag: bool

    # GSC page data
    page_url: str
    top_query: str
    impressions: int
    clicks: int
    ctr: float          # actual CTR as decimal (e.g. 0.032 = 3.2%)
    position: float     # avg position over lookback window

    # Secondary queries from GSC (sorted by impressions desc, top_query excluded).
    # These are real proven-relevant queries the page already ranks for.
    # Used to build the extended keyword tail in the title tag.
    secondary_queries: List[str] = field(default_factory=list)

    # Classification (filled by step3_classify)
    expected_ctr: float = 0.0
    ctr_gap: float = 0.0        # expected_ctr - ctr (decimal)

    # Live page content (filled by step4_fetch_meta)
    current_title: str = ""
    current_meta: str = ""
    fetch_error: str = ""

    # Competitor SERP data (filled by step4_fetch_meta)
    competitor_serps: List[CompetitorResult] = field(default_factory=list)

    # AI rewrites (filled by step5_rewrite)
    recommended_title: str = ""
    visible_portion: str = ""
    extended_portion: str = ""
    title_char_count: int = 0
    recommended_meta: str = ""
    rationale: str = ""

    # Tracking
    analysis_date: str = ""


# ── Serialization helpers ──────────────────────────────────────────────────────

def pages_to_json(pages: list) -> str:
    def _serialize(p):
        d = asdict(p)
        return d
    return json.dumps([_serialize(p) for p in pages], indent=2)


def pages_from_json(data: str) -> list:
    rows = json.loads(data)
    result = []
    for r in rows:
        competitors = [CompetitorResult(**c) for c in r.pop("competitor_serps", [])]
        p = PageOpportunity(**r)
        p.competitor_serps = competitors
        result.append(p)
    return result
