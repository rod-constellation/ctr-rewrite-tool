"""
Step 4 — Fetch Current Title/Meta and Competitor SERP Data

Most law firm sites use Cloudflare, which blocks simple HTTP fetchers.
We solve this entirely through DataForSEO so no direct page requests are needed:

Pass 1 — Top-query SERP (depth 15):
  Fetch the SERP for each page's top query. If the client's page appears in
  positions 1–15, we extract its title/meta from there. Same call also gives us
  competitor data for positions 1–5.

Pass 2 — site: SERP fallback:
  For any page not found in Pass 1, we run a `site:URL` query and scan the top 10
  results for an exact URL match. This works even when the page isn't in the organic
  top 15 for its query, because `site:` forces Google to show pages from that domain.

Both passes pull title/meta as Google currently indexes them — bypassing Cloudflare
entirely and giving us the true baseline for CTR comparison.

Returns: list[PageOpportunity] (mutated in-place)
"""

import time
import requests
from urllib.parse import urlparse

import config
from models import PageOpportunity, CompetitorResult


# ── URL helpers ────────────────────────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """Strip scheme, www, trailing slash for fuzzy URL matching."""
    try:
        p = urlparse(url.lower().strip())
        host = p.netloc.replace("www.", "")
        path = p.path.rstrip("/")
        return host + path
    except Exception:
        return url.lower().strip()


def _url_matches(page_url: str, serp_url: str) -> bool:
    return _normalize_url(page_url) == _normalize_url(serp_url)


# ── DataForSEO helpers ─────────────────────────────────────────────────────────

def _serp_call(query: str, depth: int) -> list:
    """
    Call DataForSEO Google Organic Live SERP API.
    Returns list of organic result dicts: [{position, title, meta, url}, ...]
    """
    try:
        resp = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/live/regular",
            json=[{
                "keyword":       query,
                "location_code": config.DATAFORSEO_LOCATION,
                "language_code": "en",
                "device":        "desktop",
                "os":            "windows",
                "depth":         depth,
            }],
            auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD),
            timeout=config.REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return []
        data  = resp.json()
        tasks = data.get("tasks", [])
        if not tasks or tasks[0].get("status_code") != 20000:
            return []
        items = tasks[0].get("result", [{}])[0].get("items", [])
        results = []
        organic_pos = 0
        for item in items:
            if item.get("type") != "organic":
                continue
            organic_pos += 1
            if organic_pos > depth:
                break
            results.append({
                "position": organic_pos,
                "title":    item.get("title", ""),
                "meta":     item.get("description", ""),
                "url":      item.get("url", ""),
            })
        return results
    except Exception:
        return []


def _find_own_page(page_url: str, serp_results: list) -> tuple:
    """Scan SERP results for a URL matching page_url. Returns (title, meta) or ('', '')."""
    for r in serp_results:
        if _url_matches(page_url, r["url"]):
            return r["title"], r["meta"]
    return "", ""


def _site_serp_lookup(page_url: str) -> tuple:
    """
    Fallback: query `site:{url}` in Google and scan top 10 results for a match.
    For homepages, also try `site:{domain}` without a path.
    Returns (title, meta) or ('', '').
    """
    parsed   = urlparse(page_url)
    domain   = parsed.netloc.replace("www.", "")
    path     = parsed.path.rstrip("/")
    is_home  = path == "" or path == "/"

    # Build query — for homepages use domain only, otherwise use domain + path
    if is_home:
        query = f"site:{domain}"
    else:
        query = f"site:{domain}{path}"

    results = _serp_call(query, depth=10)
    title, meta = _find_own_page(page_url, results)
    if title:
        return title, meta

    # For non-homepages: also try domain-only query in case the path query returns nothing
    if not is_home:
        results2 = _serp_call(f"site:{domain}", depth=10)
        time.sleep(config.SERP_SLEEP)
        return _find_own_page(page_url, results2)

    return "", ""


# ── Main entry point ───────────────────────────────────────────────────────────

def run(pages: list) -> list:
    """
    Entry point for Step 4.
    Mutates pages in-place. Returns the same list.
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 4 — Fetching current titles/metas and competitor SERPs")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not pages:
        return pages

    # ── Pass 1: Top-query SERP (covers positions 1–SERP_FETCH_DEPTH) ──────────
    unique_queries = list({p.top_query for p in pages if p.top_query})
    serp_cache = {}  # {query: [all_results]}

    print(f"  Pass 1 — Top-query SERP (depth {config.SERP_FETCH_DEPTH})")
    print(f"  {len(unique_queries)} unique quer(y/ies) across {len(pages)} pages\n")

    for i, query in enumerate(unique_queries, 1):
        all_results = _serp_call(query, config.SERP_FETCH_DEPTH)
        serp_cache[query] = all_results

        for page in pages:
            if page.top_query != query:
                continue
            title, meta = _find_own_page(page.page_url, all_results)
            if title:
                page.current_title = title
                page.current_meta  = meta

            # Competitor context = top SERP_RESULT_COUNT organics that aren't our page
            page.competitor_serps = [
                CompetitorResult(
                    position=r["position"],
                    title=r["title"],
                    meta=r["meta"],
                    url=r["url"],
                )
                for r in all_results
                if not _url_matches(page.page_url, r["url"])
            ][:config.SERP_RESULT_COUNT]

        found_count = sum(1 for p in pages if p.top_query == query and p.current_title)
        print(f"    [{i}/{len(unique_queries)}] '{query[:55]}'"
              f" — {len(all_results)} results, {found_count} own page(s) found")
        time.sleep(config.SERP_SLEEP)

    # ── Pass 2: site: fallback for pages still missing title ──────────────────
    missing = [p for p in pages if not p.current_title]
    if missing:
        print(f"\n  Pass 2 — site: fallback for {len(missing)} page(s) not found in Pass 1")
        for i, page in enumerate(missing, 1):
            title, meta = _site_serp_lookup(page.page_url)
            if title:
                page.current_title = title
                page.current_meta  = meta
                print(f"    [{i}/{len(missing)}] ✅ '{page.page_url[:55]}' → '{title[:50]}'")
            else:
                print(f"    [{i}/{len(missing)}] ⚠️  '{page.page_url[:55]}' — not found via site: query")
            time.sleep(config.SERP_SLEEP)

    # ── Summary ───────────────────────────────────────────────────────────────
    got_title = sum(1 for p in pages if p.current_title)
    got_meta  = sum(1 for p in pages if p.current_meta)
    got_comps = sum(1 for p in pages if p.competitor_serps)
    print(
        f"\n  ✅ Step 4 complete — "
        f"{got_title}/{len(pages)} current titles | "
        f"{got_meta}/{len(pages)} current metas | "
        f"{got_comps}/{len(pages)} competitor context."
    )
    return pages
