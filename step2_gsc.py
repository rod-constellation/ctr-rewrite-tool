"""
Step 2 — Pull GSC Page Data

For each active client, queries Google Search Console for 90-day page analytics.
Aggregates page-level metrics from page+query dimensions, applies position/impression
filters, then enforces query ownership to eliminate cannibalization noise.

Query ownership rule:
  For each page's top query, that page must have MORE impressions for the query
  than any other page on the same domain. If a secondary page is claiming a query
  that the homepage or a stronger page already owns, it gets dropped.
  The canonical (highest-impression) page for a query is the one we rewrite.

Returns: list[PageOpportunity] (canonical pages only, not yet classified)
"""

import re
import time
import datetime
from collections import defaultdict
from typing import Optional

import config
from models import ClientRecord, PageOpportunity


# ── Auth (identical to Striking Distance step2_gsc.py) ────────────────────────

def _build_gsc_service():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=config.GOOGLE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        scopes=config.GOOGLE_SCOPES,
    )
    creds.refresh(Request())
    return build("searchconsole", "v1", credentials=creds)


def _list_gsc_properties(service) -> list:
    result = service.sites().list().execute()
    return [s["siteUrl"] for s in result.get("siteEntry", [])]


def _match_domain_to_property(domain: str, properties: list) -> Optional[str]:
    if not domain:
        return None
    candidates = [
        f"sc-domain:{domain}",
        f"https://www.{domain}/",
        f"https://{domain}/",
        f"http://www.{domain}/",
        f"http://{domain}/",
    ]
    prop_set = set(properties)
    for candidate in candidates:
        if candidate in prop_set:
            return candidate
    for prop in properties:
        cleaned = re.sub(r"^sc-domain:|^https?://(www\.)?", "", prop).rstrip("/")
        if cleaned == domain or cleaned.endswith(f".{domain}"):
            return prop
    return None


# ── GSC query ─────────────────────────────────────────────────────────────────

def _query_pages(service, gsc_property: str) -> list:
    """
    Query GSC for page+query combinations over the lookback window.
    Returns raw rows: [{page, query, impressions, clicks, position}, ...]
    """
    end_date   = datetime.date.today().isoformat()
    start_date = (datetime.date.today() - datetime.timedelta(days=config.GSC_LOOKBACK_DAYS)).isoformat()

    all_rows = []
    start_row = 0

    while True:
        try:
            resp = service.searchanalytics().query(
                siteUrl=gsc_property,
                body={
                    "startDate":  start_date,
                    "endDate":    end_date,
                    "dimensions": ["page", "query"],
                    "rowLimit":   config.GSC_ROW_LIMIT,
                    "startRow":   start_row,
                }
            ).execute()
        except Exception as e:
            print(f"    ⚠️  GSC query error: {e}")
            break

        rows = resp.get("rows", [])
        if not rows:
            break

        for row in rows:
            page, query = row["keys"]
            all_rows.append({
                "page":        page,
                "query":       query,
                "impressions": int(row.get("impressions", 0)),
                "clicks":      int(row.get("clicks", 0)),
                "position":    float(row.get("position", 0)),
            })

        if len(rows) < config.GSC_ROW_LIMIT:
            break
        start_row += config.GSC_ROW_LIMIT

    return all_rows


def _aggregate_pages(raw_rows: list) -> tuple:
    """
    Aggregate page+query rows into page-level records.
    Also builds a query→leader map: for each query, which page has the most impressions?
    Collects secondary queries (all queries with >= GSC_SECONDARY_MIN_IMPRESSIONS,
    sorted by impressions desc, excluding the top query).

    Returns:
      pages: list of page dicts with aggregated stats + secondary_queries
      query_leader: {query: page_url_with_most_impressions}
    """
    page_data = {}
    # Track impressions per query per page: {query: {page: impressions}}
    query_page_imps = defaultdict(lambda: defaultdict(int))
    # Track all (query, impressions) pairs per page for secondary query extraction
    page_query_imps = defaultdict(lambda: defaultdict(int))

    for row in raw_rows:
        page  = row["page"]
        query = row["query"]
        imps  = row["impressions"]

        if page not in page_data:
            page_data[page] = {
                "impressions":    0,
                "clicks":         0,
                "weighted_pos":   0.0,
                "top_query":      "",
                "top_query_imps": 0,
            }
        pd = page_data[page]
        pd["impressions"]  += imps
        pd["clicks"]       += row["clicks"]
        pd["weighted_pos"] += row["position"] * imps

        if imps > pd["top_query_imps"]:
            pd["top_query"]      = query
            pd["top_query_imps"] = imps

        query_page_imps[query][page] += imps
        page_query_imps[page][query] += imps

    # Determine the canonical (leader) page for each query
    query_leader = {
        query: max(page_imps, key=page_imps.get)
        for query, page_imps in query_page_imps.items()
    }

    pages = []
    for page, pd in page_data.items():
        imp = pd["impressions"]
        if imp == 0:
            continue

        top_query = pd["top_query"]

        # Secondary queries: all queries above the impression floor, excluding top_query,
        # sorted by impressions desc, capped at GSC_SECONDARY_QUERIES_COUNT
        all_queries = sorted(page_query_imps[page].items(), key=lambda x: -x[1])
        secondary = [
            q for q, q_imps in all_queries
            if q != top_query and q_imps >= config.GSC_SECONDARY_MIN_IMPRESSIONS
        ][:config.GSC_SECONDARY_QUERIES_COUNT]

        pages.append({
            "page":              page,
            "top_query":         top_query,
            "top_query_imps":    pd["top_query_imps"],
            "impressions":       imp,
            "clicks":            pd["clicks"],
            "ctr":               pd["clicks"] / imp,
            "position":          round(pd["weighted_pos"] / imp, 2),
            "secondary_queries": secondary,
        })

    return pages, query_leader


def _filter_pages(pages: list, query_leader: dict) -> tuple:
    """
    Two-stage filter:
      1. Position range and impression floor (configured in config.py)
      2. Query ownership — keep a page only if it is the canonical page for its
         top query (i.e., no other page on this domain has more impressions for
         that query). Secondary pages that share a query with a stronger page
         are dropped and logged as potential cannibalization signals.

    Returns:
      kept: list of pages that pass both filters
      cannibalized: list of (page, top_query, canonical_page) for logging
    """
    in_range = [
        p for p in pages
        if p["impressions"] >= config.GSC_MIN_IMPRESSIONS
        and config.GSC_MIN_POSITION <= p["position"] <= config.GSC_MAX_POSITION
        and not any(p["page"].lower().endswith(ext) for ext in config.EXCLUDED_URL_EXTENSIONS)
    ]

    kept = []
    cannibalized = []

    for p in in_range:
        leader = query_leader.get(p["top_query"], p["page"])
        if leader == p["page"]:
            kept.append(p)
        else:
            cannibalized.append((p["page"], p["top_query"], leader))

    return kept, cannibalized


# ── Main entry point ───────────────────────────────────────────────────────────

def run(clients: list) -> list:
    """
    Entry point for Step 2.
    Returns list[PageOpportunity] (canonical pages only, across all clients).
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 2 — Pulling GSC page data")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    today = datetime.date.today().isoformat()

    try:
        service = _build_gsc_service()
    except Exception as e:
        print(f"  ❌ Could not connect to GSC: {e}")
        return []

    properties = _list_gsc_properties(service)
    print(f"  GSC account has access to {len(properties)} propert(y/ies).\n")

    domain_map = {}
    for client in clients:
        if client.domain and client.domain not in domain_map:
            prop = _match_domain_to_property(client.domain, properties)
            domain_map[client.domain] = prop
            if not prop:
                print(f"  ⚠️  No GSC property found for: {client.domain} ({client.client_name})")

    all_pages = []
    total_cannibalized = 0
    total_clients = len(clients)

    for ci, client in enumerate(clients, 1):
        gsc_prop = domain_map.get(client.domain)
        print(f"  [{ci}/{total_clients}] {client.client_name} ({client.domain})", end="")

        if not gsc_prop:
            print(" — no GSC property, skipping")
            continue

        try:
            raw_rows             = _query_pages(service, gsc_prop)
            aggregated, q_leader = _aggregate_pages(raw_rows)
            kept, cannibalized   = _filter_pages(aggregated, q_leader)

            canon_note = ""
            if cannibalized:
                total_cannibalized += len(cannibalized)
                canon_note = f" | ⚠️  {len(cannibalized)} cannibalized (secondary pages dropped)"

            print(
                f" — {len(raw_rows)} rows → {len(aggregated)} pages"
                f" → {len(kept)} in range{canon_note}"
            )

            # Log cannibalization details for visibility
            for page_url, query, canonical in cannibalized[:3]:
                print(f"       ↳ '{query}': {page_url.split('/')[-2] or '/'} is secondary to {canonical.split('/')[-2] or '/'}")
            if len(cannibalized) > 3:
                print(f"       ↳ ... and {len(cannibalized) - 3} more")

            for p in kept:
                all_pages.append(PageOpportunity(
                    client_name=client.client_name,
                    domain=client.domain,
                    strategist=client.strategist,
                    is_red_flag=client.is_red_flag,
                    page_url=p["page"],
                    top_query=p["top_query"],
                    impressions=p["impressions"],
                    clicks=p["clicks"],
                    ctr=p["ctr"],
                    position=p["position"],
                    secondary_queries=p.get("secondary_queries", []),
                    analysis_date=today,
                ))

        except Exception as e:
            print(f" — ❌ error: {e}")

        time.sleep(config.GSC_SLEEP)

    print(
        f"\n  ✅ Step 2 complete — {len(all_pages)} canonical pages across "
        f"{len({p.client_name for p in all_pages})} client(s)."
    )
    if total_cannibalized:
        print(
            f"  ⚠️  {total_cannibalized} secondary pages dropped (query cannibalization)."
            f" These may be worth reviewing for content consolidation."
        )
    return all_pages
