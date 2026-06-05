"""
Title & Meta Pattern Analysis Script

Run this BEFORE the full rewrite run to understand:
  1. What your clients' current titles and metas look like (patterns, CTAs, separators)
  2. What top-ranking competitor titles look like in the same SERPs
  3. What conventions work at positions 1-3 vs what your clients are doing

Usage:
  python3 analyze_titles.py                  # Pull fresh GSC data + sample pages
  python3 analyze_titles.py --sample 40      # Control sample size (default: 40)
  python3 analyze_titles.py --client "Dressie Law Firm"   # Focus on one client

Output:
  - Printed report to terminal
  - reports/title_analysis_YYYY-MM-DD.txt  (full text report)
  - reports/title_analysis_YYYY-MM-DD.json (raw data for reference)
"""

import argparse
import asyncio
import json
import os
import re
import time
import random
from collections import Counter, defaultdict
from datetime import date

import requests

try:
    import aiohttp
    from bs4 import BeautifulSoup
    HAS_ASYNC = True
except ImportError:
    HAS_ASYNC = False

import config


# ── Practice area detection from URL / query ──────────────────────────────────

PRACTICE_AREA_PATTERNS = [
    ("Personal Injury",    r"personal.injury|car.accident|auto.accident|truck.accident|slip.and.fall|motorcycle|wrongful.death|injury"),
    ("DUI / Criminal",     r"\bdui\b|drunk.driv|dwi|criminal.defense|criminal.lawyer|assault|theft|drug.crime|felony|misdemeanor"),
    ("Family Law",         r"divorce|family.law|custody|child.support|alimony|adoption|guardian"),
    ("Estate Planning",    r"estate.plan|probate|will\b|trust\b|elder.law|wills.and.trust"),
    ("Immigration",        r"immigration|visa\b|deportation|green.card|citizenship|asylum"),
    ("Workers Comp",       r"workers.comp|workplace.injur|work.injur|workmans.comp"),
    ("Bankruptcy",         r"bankruptcy|chapter.7|chapter.13|debt.relief"),
    ("Real Estate",        r"real.estate.law|landlord|tenant|property.law"),
    ("Employment",         r"employment.law|wrongful.termination|discrimination|harassment"),
    ("Business Law",       r"business.law|corporate|contract.disput"),
]

def detect_practice_area(url: str, query: str) -> str:
    combined = (url + " " + query).lower()
    for area, pattern in PRACTICE_AREA_PATTERNS:
        if re.search(pattern, combined):
            return area
    return "Other"


# ── Pattern detection helpers ─────────────────────────────────────────────────

SEPARATOR_PATTERNS = [
    ("Pipe ( | )", r" \| "),
    ("Dash ( - )", r" - | – | — "),
    ("Colon ( : )", r": "),
]

CTA_KEYWORDS = [
    ("Free Consultation",  r"free\s+consult"),
    ("Free Case Review",   r"free\s+case\s+review"),
    ("Call 24/7",          r"24[/\s]?7|available\s+24"),
    ("No Fee Unless Win",  r"no\s+fee\s+unless|contingency|no\s+recovery"),
    ("Call Now/Today",     r"call\s+(now|today|us)"),
    ("Schedule",           r"schedul"),
    ("Get Help",           r"get\s+help"),
]

def detect_separator(title: str) -> str:
    for label, pattern in SEPARATOR_PATTERNS:
        if re.search(pattern, title):
            return label
    return "None"

def detect_ctas(title: str) -> list:
    found = []
    t = title.lower()
    for label, pattern in CTA_KEYWORDS:
        if re.search(pattern, t):
            found.append(label)
    return found or ["No CTA"]

def is_keyword_first(title: str, query: str) -> bool:
    """Check if title starts with a word from the top query."""
    if not title or not query:
        return False
    first_word = title.split()[0].lower().strip("\"'")
    query_words = set(query.lower().split())
    return first_word in query_words

def is_hook_first(title: str) -> bool:
    """Starts with a question or emotional word."""
    t = title.lower().strip()
    return (t.startswith(("hurt", "injured", "arrested", "facing", "need", "looking",
                           "got", "been", "dealing", "struggling", "charged")) or
            t.endswith("?") or t.startswith("?"))

def has_geo(title: str, url: str) -> bool:
    """Very rough check — title contains a capitalized word not in query that could be a city/state."""
    # This is heuristic — we'll just check if there's something that looks like a location
    us_states_abbr = r'\b(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b'
    return bool(re.search(us_states_abbr, title))

def char_bucket(n: int) -> str:
    if n < 40:    return "< 40 (too short)"
    if n <= 55:   return "40–55 (good)"
    if n <= 65:   return "56–65 (ideal for visible)"
    if n <= 80:   return "66–80 (slightly over)"
    return "> 80 (too long for visible)"


# ── Data collection ───────────────────────────────────────────────────────────

def fetch_current_titles_sync(pages: list) -> dict:
    """Synchronous fallback title fetcher (one at a time)."""
    results = {}
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    for p in pages:
        url = p.page_url if hasattr(p, "page_url") else p["page_url"]
        try:
            resp = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
            soup = BeautifulSoup(resp.text, "lxml")
            title_tag = soup.find("title")
            meta_tag  = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
            results[url] = {
                "title": title_tag.get_text(strip=True) if title_tag else "",
                "meta":  meta_tag.get("content", "").strip() if meta_tag else "",
            }
        except Exception as e:
            results[url] = {"title": "", "meta": "", "error": str(e)[:60]}
        time.sleep(0.3)
    return results


async def _fetch_one(session, page, sem: asyncio.Semaphore, results: dict):
    url = page.page_url if hasattr(page, "page_url") else page["page_url"]
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8),
                                   headers=headers, allow_redirects=True, ssl=False) as resp:
                html = await resp.text(errors="replace")
                soup = BeautifulSoup(html, "lxml")
                t = soup.find("title")
                m = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
                results[url] = {
                    "title": t.get_text(strip=True) if t else "",
                    "meta":  m.get("content", "").strip() if m else "",
                }
        except Exception as e:
            results[url] = {"title": "", "meta": "", "error": str(e)[:60]}


async def fetch_current_titles_async(pages: list) -> dict:
    results = {}
    sem = asyncio.Semaphore(8)
    connector = aiohttp.TCPConnector(ssl=False, limit=8)
    async with aiohttp.ClientSession(connector=connector) as session:
        await asyncio.gather(*[_fetch_one(session, p, sem, results) for p in pages])
    return results


def fetch_serp_titles(query: str) -> list:
    """DataForSEO SERP for one query. Returns list of {position, title, meta, url}."""
    url = "https://api.dataforseo.com/v3/serp/google/organic/live/regular"
    payload = [{
        "keyword":       query,
        "location_code": config.DATAFORSEO_LOCATION,
        "language_code": "en",
        "device":        "desktop",
        "os":            "windows",
        "depth":         10,
    }]
    try:
        resp = requests.post(url, json=payload,
                             auth=(config.DATAFORSEO_LOGIN, config.DATAFORSEO_PASSWORD),
                             timeout=20)
        if resp.status_code != 200:
            return []
        data = resp.json()
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
            if organic_pos > 5:
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


# ── GSC pull (abbreviated — only for fresh runs) ─────────────────────────────

def pull_sample_pages(sample_size: int, target_client: str = None) -> list:
    """Run Steps 1-3 to get flagged pages, then sample them."""
    print("  Running Steps 1–3 to get candidate pages...")

    import step1_clients, step2_gsc, step3_classify
    clients = step1_clients.run()
    if target_client:
        clients = [c for c in clients if target_client.lower() in c.client_name.lower()]
        if not clients:
            print(f"  No client matching '{target_client}'")
            return []

    pages = step2_gsc.run(clients)
    flagged = step3_classify.run(pages)
    return flagged


def sample_pages(flagged: list, sample_size: int) -> list:
    """Select a representative sample balanced across clients and practice areas."""
    # Group by client
    by_client = defaultdict(list)
    for p in flagged:
        by_client[p.client_name].append(p)

    # Sort each client's pages by CTR gap (worst first)
    for name in by_client:
        by_client[name].sort(key=lambda p: -p.ctr_gap)

    # Take top N per client, then shuffle
    per_client = max(1, sample_size // max(len(by_client), 1))
    per_client = min(per_client, 5)  # cap at 5 per client

    sample = []
    for name, pages in sorted(by_client.items()):
        sample.extend(pages[:per_client])

    # If still short, fill from remaining
    if len(sample) < sample_size:
        already_urls = {p.page_url for p in sample}
        extras = [p for p in flagged if p.page_url not in already_urls]
        random.shuffle(extras)
        sample.extend(extras[:sample_size - len(sample)])

    return sample[:sample_size]


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze_titles(titles_map: dict, pages: list) -> dict:
    """Analyze our clients' current title patterns."""
    records = []
    for p in pages:
        info = titles_map.get(p.page_url, {})
        title = info.get("title", "")
        meta  = info.get("meta", "")
        if not title:
            continue
        records.append({
            "client":        p.client_name,
            "url":           p.page_url,
            "query":         p.top_query,
            "practice_area": detect_practice_area(p.page_url, p.top_query),
            "title":         title,
            "meta":          meta,
            "char_count":    len(title),
            "separator":     detect_separator(title),
            "ctas":          detect_ctas(title),
            "keyword_first": is_keyword_first(title, p.top_query),
            "hook_first":    is_hook_first(title),
            "has_geo":       has_geo(title, p.page_url),
            "position":      p.position,
            "actual_ctr":    p.ctr,
        })
    return records


def analyze_serp_titles(serp_map: dict) -> list:
    """Flatten all SERP results into a list with query attached."""
    records = []
    for query, results in serp_map.items():
        for r in results:
            title = r.get("title", "")
            if not title:
                continue
            records.append({
                "query":         query,
                "practice_area": detect_practice_area(r.get("url", ""), query),
                "position":      r["position"],
                "title":         title,
                "meta":          r.get("meta", ""),
                "char_count":    len(title),
                "separator":     detect_separator(title),
                "ctas":          detect_ctas(title),
                "keyword_first": is_keyword_first(title, query),
                "hook_first":    is_hook_first(title),
                "has_geo":       has_geo(title, r.get("url", "")),
            })
    return records


# ── Report builder ─────────────────────────────────────────────────────────────

def pct(n, total):
    if total == 0: return "0%"
    return f"{n/total*100:.0f}%"

def counter_table(items: list, label: str, total: int) -> str:
    c = Counter(items)
    lines = [f"\n{label}:"]
    for val, count in c.most_common():
        lines.append(f"  {val:<35} {count:>3} ({pct(count, total)})")
    return "\n".join(lines)

def build_report(client_records: list, serp_records: list, today: str) -> str:
    lines = []
    lines.append("═" * 70)
    lines.append("  TITLE & META PATTERN ANALYSIS")
    lines.append(f"  {today}  |  {len(client_records)} client pages  |  {len(serp_records)} SERP competitor titles")
    lines.append("═" * 70)

    # ── CLIENT TITLES ────────────────────────────────────────────────────────
    lines.append("\n" + "─" * 70)
    lines.append("  YOUR CLIENTS' CURRENT TITLE TAGS")
    lines.append("─" * 70)
    n = len(client_records)

    separators = [r["separator"] for r in client_records]
    lines.append(counter_table(separators, "Separator Usage", n))

    all_ctas = [cta for r in client_records for cta in r["ctas"]]
    lines.append(counter_table(all_ctas, "CTA Usage", n))

    char_buckets = [char_bucket(r["char_count"]) for r in client_records]
    lines.append(counter_table(char_buckets, "Title Character Count", n))

    formats = []
    for r in client_records:
        if r["hook_first"]:    formats.append("Hook/question-first")
        elif r["keyword_first"]: formats.append("Keyword-first")
        else:                  formats.append("Other (firm name or brand first)")
    lines.append(counter_table(formats, "Title Format", n))

    geo_count = sum(1 for r in client_records if r["has_geo"])
    lines.append(f"\nGeo in Title:  {geo_count}/{n} ({pct(geo_count, n)})")

    # Practice area breakdown
    by_area = defaultdict(list)
    for r in client_records:
        by_area[r["practice_area"]].append(r)

    lines.append("\n\nSAMPLE TITLES BY PRACTICE AREA (client pages):\n")
    for area in sorted(by_area):
        lines.append(f"  [{area}]")
        for r in by_area[area][:3]:
            lines.append(f"    \"{r['title']}\"  ({r['char_count']} chars)")
            if r["meta"]:
                lines.append(f"    META: \"{r['meta'][:120]}\"")
        lines.append("")

    # ── SERP COMPETITOR TITLES ────────────────────────────────────────────────
    lines.append("\n" + "─" * 70)
    lines.append("  TOP-RANKING COMPETITOR TITLES (Positions 1–5)")
    lines.append("─" * 70)
    ns = len(serp_records)

    if ns == 0:
        lines.append("  (No SERP data collected — DataForSEO may be unavailable)")
    else:
        serp_seps = [r["separator"] for r in serp_records]
        lines.append(counter_table(serp_seps, "Separator Usage", ns))

        serp_ctas = [cta for r in serp_records for cta in r["ctas"]]
        lines.append(counter_table(serp_ctas, "CTA Usage", ns))

        serp_chars = [char_bucket(r["char_count"]) for r in serp_records]
        lines.append(counter_table(serp_chars, "Character Count", ns))

        serp_formats = []
        for r in serp_records:
            if r["hook_first"]:      serp_formats.append("Hook/question-first")
            elif r["keyword_first"]: serp_formats.append("Keyword-first")
            else:                    serp_formats.append("Other")
        lines.append(counter_table(serp_formats, "Format", ns))

        serp_geo = sum(1 for r in serp_records if r["has_geo"])
        lines.append(f"\nGeo in Title:  {serp_geo}/{ns} ({pct(serp_geo, ns)})")

        # By position breakdown
        lines.append("\n\nPATTERN BY POSITION (top results):\n")
        for pos in [1, 2, 3]:
            pos_records = [r for r in serp_records if r["position"] == pos]
            if not pos_records:
                continue
            pos_ctas = Counter(cta for r in pos_records for cta in r["ctas"])
            pos_seps = Counter(r["separator"] for r in pos_records)
            top_cta = pos_ctas.most_common(1)[0][0] if pos_ctas else "—"
            top_sep = pos_seps.most_common(1)[0][0] if pos_seps else "—"
            kw_pct  = pct(sum(1 for r in pos_records if r["keyword_first"]), len(pos_records))
            lines.append(f"  Position {pos}: {len(pos_records)} titles  |  top sep: {top_sep}  |  top CTA: {top_cta}  |  keyword-first: {kw_pct}")

        # Sample SERP titles by practice area
        serp_by_area = defaultdict(list)
        for r in serp_records:
            serp_by_area[r["practice_area"]].append(r)

        lines.append("\n\nSAMPLE COMPETITOR TITLES BY PRACTICE AREA:\n")
        for area in sorted(serp_by_area):
            lines.append(f"  [{area}]")
            area_records = sorted(serp_by_area[area], key=lambda r: r["position"])
            for r in area_records[:4]:
                lines.append(f"    #{r['position']}  \"{r['title']}\"  ({r['char_count']} chars)")
            lines.append("")

    # ── SIDE BY SIDE: QUERIES WHERE WE HAVE BOTH ─────────────────────────────
    client_by_query = {r["query"]: r for r in client_records}
    serp_by_query   = defaultdict(list)
    for r in serp_records:
        serp_by_query[r["query"]].append(r)

    overlap = [q for q in client_by_query if q in serp_by_query]
    if overlap:
        lines.append("\n" + "─" * 70)
        lines.append("  SIDE-BY-SIDE: OUR PAGE vs. TOP COMPETITORS (same query)")
        lines.append("─" * 70)
        for query in overlap[:8]:
            client_r = client_by_query[query]
            lines.append(f"\n  Query: \"{query}\"  (pos {client_r['position']:.1f}, CTR {client_r['actual_ctr']*100:.1f}%)")
            lines.append(f"  OUR PAGE:  \"{client_r['title']}\"  ({client_r['char_count']} chars)")
            for comp in sorted(serp_by_query[query], key=lambda r: r["position"])[:3]:
                lines.append(f"  #{comp['position']} RANK:   \"{comp['title']}\"  ({comp['char_count']} chars)")

    # ── OBSERVATIONS ──────────────────────────────────────────────────────────
    lines.append("\n\n" + "─" * 70)
    lines.append("  OBSERVATIONS (auto-generated — review and adjust)")
    lines.append("─" * 70)

    if n > 0:
        top_client_sep = Counter(separators).most_common(1)[0][0]
        lines.append(f"\n  Your clients mostly use: {top_client_sep}")

    if ns > 0:
        top_serp_sep = Counter(serp_seps).most_common(1)[0][0]
        top_serp_cta = Counter(serp_ctas).most_common(1)[0][0]
        kw_first_pct = pct(sum(1 for r in serp_records if r["keyword_first"]), ns)
        hook_pct     = pct(sum(1 for r in serp_records if r["hook_first"]), ns)

        lines.append(f"  Top-ranking titles mostly use: {top_serp_sep} separators")
        lines.append(f"  Most common top-ranking CTA: {top_serp_cta}")
        lines.append(f"  Keyword-first format: {kw_first_pct} of top-ranking titles")
        lines.append(f"  Hook/question-first: {hook_pct} of top-ranking titles")
        lines.append(f"  Geo in title: {pct(serp_geo, ns)} of top-ranking titles")

    lines.append("\n  NEXT STEP:")
    lines.append("  Review the patterns above, then tell Claude which format to standardize.")
    lines.append("  The rewrite prompt will be saved to config/rewrite_prompt.md —")
    lines.append("  a plain text file you can edit anytime without touching Python code.")

    lines.append("\n" + "═" * 70 + "\n")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyze title/meta patterns before running rewrites")
    parser.add_argument("--sample",  type=int, default=40, help="Number of pages to sample (default: 40)")
    parser.add_argument("--client",  type=str, default=None, help="Focus on a specific client name")
    parser.add_argument("--no-serp", action="store_true", help="Skip DataForSEO SERP fetching")
    args = parser.parse_args()

    today = date.today().strftime("%Y-%m-%d")
    os.makedirs(config.REPORTS_DIR, exist_ok=True)

    print("\n" + "═" * 70)
    print("  Title & Meta Pattern Analysis")
    print("═" * 70 + "\n")

    # ── Step 1: Get pages ─────────────────────────────────────────────────────
    # Try to load from checkpoint first (if a previous --dry-run was done)
    checkpoint_path = os.path.join(config.BASE_DIR, ".checkpoint.json")
    flagged = []

    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path) as f:
                cp = json.load(f)
            if cp.get("completed_step", 0) >= 3 and "flagged" in cp.get("data", {}):
                from models import pages_from_json
                flagged = pages_from_json(cp["data"]["flagged"])
                print(f"  Loaded {len(flagged)} flagged pages from checkpoint (step {cp['completed_step']})")
        except Exception:
            pass

    if not flagged:
        print("  No checkpoint found — running Steps 1–3 to collect pages...")
        flagged = pull_sample_pages(args.sample, args.client)

    if args.client:
        flagged = [p for p in flagged if args.client.lower() in p.client_name.lower()]

    if not flagged:
        print("  No pages found. Run python3 main.py --dry-run first.")
        return

    # Sample
    sample = sample_pages(flagged, args.sample)
    print(f"  Sample: {len(sample)} pages across {len({p.client_name for p in sample})} clients\n")

    # ── Step 2: Fetch current titles ──────────────────────────────────────────
    print(f"  Fetching current titles from {len(sample)} live pages...")
    if HAS_ASYNC:
        titles_map = asyncio.run(fetch_current_titles_async(sample))
    else:
        titles_map = fetch_current_titles_sync(sample)

    fetched = sum(1 for v in titles_map.values() if v.get("title"))
    print(f"  {fetched}/{len(sample)} pages returned a title\n")

    # ── Step 3: Fetch SERP competitor titles ──────────────────────────────────
    serp_map = {}
    if not args.no_serp:
        unique_queries = list({p.top_query for p in sample if p.top_query})[:30]
        print(f"  Fetching SERP competitor titles for {len(unique_queries)} queries...")
        for i, query in enumerate(unique_queries, 1):
            results = fetch_serp_titles(query)
            serp_map[query] = results
            print(f"    [{i}/{len(unique_queries)}] \"{query[:55]}\" — {len(results)} results")
            time.sleep(config.SERP_SLEEP)
        print()

    # ── Step 4: Analyze ───────────────────────────────────────────────────────
    client_records = analyze_titles(titles_map, sample)
    serp_records   = analyze_serp_titles(serp_map)

    # Attach practice area to sample pages
    for p in sample:
        p_rec = next((r for r in client_records if r["url"] == p.page_url), None)

    # ── Step 5: Build and output report ──────────────────────────────────────
    report = build_report(client_records, serp_records, today)
    print(report)

    # Save text report
    txt_path = os.path.join(config.REPORTS_DIR, f"title_analysis_{today}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Report saved: {txt_path}")

    # Save raw JSON
    json_path = os.path.join(config.REPORTS_DIR, f"title_analysis_{today}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "date":           today,
            "sample_size":    len(sample),
            "client_titles":  client_records,
            "serp_titles":    serp_records,
        }, f, indent=2)
    print(f"  Raw data saved: {json_path}\n")


if __name__ == "__main__":
    main()
