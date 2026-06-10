"""
Step 3 — Build CTR Curve, Classify Pages, and Filter to Service Pages

Builds a CTR-by-position benchmark from our own client data (internal curve).
Falls back to published benchmarks for any position bucket with insufficient samples.

Flags pages where actual_CTR <= CTR_THRESHOLD_RATIO * expected_CTR.

Then filters to service/transactional pages only:
  - Query contains hire-intent signals ("attorney", "lawyer", "law firm", etc.)
  - AND URL does not indicate blog/informational content (/blog/, /news/, etc.)

Blog posts and informational articles are excluded — CTR improvements there
don't meaningfully drive leads, and the extended title strategy doesn't fit them.

Returns: list[PageOpportunity] (service pages only, flagged, sorted by ctr_gap desc)
"""

import statistics
import math

import config
from models import PageOpportunity


def _build_internal_curve(pages: list) -> dict:
    """
    Group pages by floor(position) and compute median CTR per bucket.
    Returns {position_int: median_ctr} for buckets with >= INTERNAL_CURVE_MIN_SAMPLES pages.
    """
    buckets = {}
    for p in pages:
        bucket = math.floor(p.position)
        buckets.setdefault(bucket, []).append(p.ctr)

    curve = {}
    for pos, ctrs in buckets.items():
        if len(ctrs) >= config.INTERNAL_CURVE_MIN_SAMPLES:
            curve[pos] = statistics.median(ctrs)

    return curve


def _expected_ctr(position: float, internal_curve: dict) -> float:
    """
    Look up expected CTR for a given position.
    Prefers internal curve; falls back to config.CTR_BENCHMARK.
    """
    bucket = math.floor(position)

    if bucket in internal_curve:
        return internal_curve[bucket]

    if bucket in config.CTR_BENCHMARK:
        return config.CTR_BENCHMARK[bucket]

    keys = sorted(config.CTR_BENCHMARK.keys())
    if bucket <= keys[0]:
        return config.CTR_BENCHMARK[keys[0]]
    if bucket >= keys[-1]:
        return config.CTR_BENCHMARK[keys[-1]]

    lower = max(k for k in keys if k <= bucket)
    upper = min(k for k in keys if k >= bucket)
    if lower == upper:
        return config.CTR_BENCHMARK[lower]
    t = (bucket - lower) / (upper - lower)
    return config.CTR_BENCHMARK[lower] + t * (config.CTR_BENCHMARK[upper] - config.CTR_BENCHMARK[lower])


def is_service_page(page: PageOpportunity) -> bool:
    """
    Returns True if this page targets a hire-intent (service/transactional) query.

    Logic (either condition passes):
      1. Top query contains any SERVICE_QUERY_KEYWORDS ("attorney", "lawyer", etc.)
      2. Top query doesn't have service keywords BUT URL doesn't have blog patterns
         AND the query contains a known practice area term (implies a service page
         without "attorney" literally in the query — e.g. "DUI defense Chicago")

    Returns False for:
      - Blog posts, news articles, FAQ pages, resource guides
      - Informational queries with no hire intent
    """
    query = (page.top_query or "").lower()
    url   = (page.page_url  or "").lower()

    # Hard exclude: URL has blog/info patterns
    for pattern in config.BLOG_URL_PATTERNS:
        if pattern in url:
            return False

    # Pass: query has explicit hire-intent keywords
    for kw in config.SERVICE_QUERY_KEYWORDS:
        if kw in query:
            return True

    # Secondary pass: query contains a practice area term — likely a service page
    # where the searcher dropped "lawyer/attorney" (e.g. "DUI Chicago", "car accident Denver")
    PRACTICE_TERMS = [
        "dui", "dwi", "personal injury", "car accident", "auto accident",
        "truck accident", "slip and fall", "wrongful death", "criminal defense",
        "divorce", "family law", "custody", "bankruptcy", "estate planning",
        "workers comp", "employment law", "immigration", "real estate law",
        "drug charge", "assault charge", "criminal charge",
    ]
    for term in PRACTICE_TERMS:
        if term in query:
            return True

    return False


def run(pages: list) -> list:
    """
    Entry point for Step 3.
    Returns list[PageOpportunity] — service pages only, flagged, sorted by ctr_gap desc.
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 3 — Building CTR curve and classifying pages")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not pages:
        print("  No pages to classify.")
        return []

    # Build internal curve from all candidate pages (before filtering)
    internal_curve = _build_internal_curve(pages)
    if internal_curve:
        print(f"  Internal CTR curve built from {len(pages)} pages ({len(internal_curve)} position bucket(s)).")
        for pos in sorted(internal_curve):
            print(f"    Position {pos}: {internal_curve[pos]*100:.2f}% (internal)")
    else:
        print(f"  Not enough data for internal curve (<{config.INTERNAL_CURVE_MIN_SAMPLES} pages per bucket).")
        print("  Using published benchmark table for all positions.")

    # Classify each page (compute expected CTR and gap for all)
    threshold = config.CTR_THRESHOLD_RATIO
    below_curve = []

    for page in pages:
        exp_ctr = _expected_ctr(page.position, internal_curve)
        gap     = exp_ctr - page.ctr

        page.expected_ctr = exp_ctr
        page.ctr_gap      = gap

        if page.ctr <= threshold * exp_ctr:
            below_curve.append(page)

    # Filter to service/transactional pages only
    flagged      = [p for p in below_curve if is_service_page(p)]
    info_skipped = len(below_curve) - len(flagged)

    flagged.sort(key=lambda p: (-p.ctr_gap, p.client_name))

    pct_of_candidates = len(flagged) / len(pages) * 100 if pages else 0
    print(
        f"\n  Below-curve pages: {len(below_curve)}/{len(pages)} "
        f"(actual CTR ≤ {int(threshold*100)}% of expected)"
    )
    print(
        f"  Service pages (rewrite candidates): {len(flagged)}"
    )
    print(
        f"  Informational/blog pages skipped:   {info_skipped} "
        f"(no hire intent — title rewrites won't drive leads)"
    )
    print(
        f"  Note: PDFs/docs filtered in Step 2 (file extensions — not editable via CMS)"
    )

    if flagged:
        by_strategist = {}
        for p in flagged:
            by_strategist.setdefault(p.strategist, 0)
            by_strategist[p.strategist] += 1
        print("\n  Service pages per strategist:")
        for strat, count in sorted(by_strategist.items()):
            print(f"    {strat}: {count}")

    print(f"\n  ✅ Step 3 complete — {len(flagged)} service pages queued for rewrite.")
    return flagged
