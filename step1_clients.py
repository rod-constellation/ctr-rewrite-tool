"""
Step 1 — Build Active Client List

Pulls active projects from Ahrefs, maps each to a strategist and red-flag status.
Reuses the same filter/matching logic as Striking Distance Keywords Tactic.

Returns: list[ClientRecord]
"""

import csv
import io
import os
import re
import sys
import time
import json
import requests
from difflib import get_close_matches
from urllib.parse import urlparse

import config
from models import ClientRecord


ALIASES_FILE      = os.path.join(config.BASE_DIR, "name_aliases.csv")
MANUAL_ASSIGN_FILE = os.path.join(config.BASE_DIR, "manual_strategist_assignments.csv")
EXCLUDED_FILE     = os.path.join(config.BASE_DIR, "excluded_clients.txt")


# ── Ahrefs helpers (same as Striking Distance step1_ahrefs.py) ─────────────────

def _ahrefs_headers() -> dict:
    return {"Authorization": f"Bearer {config.AHREFS_API_KEY}", "Accept": "application/json"}


def _get_with_retry(url: str, params: dict = None) -> requests.Response:
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=_ahrefs_headers(), params=params, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code in (429, 503):
                wait = config.BACKOFF_BASE ** attempt
                print(f"      ⏳ Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            if attempt < config.MAX_RETRIES:
                wait = config.BACKOFF_BASE ** attempt
                print(f"      ⚠️  Request error ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    return resp


def _fetch_ahrefs_projects() -> list:
    url = f"{config.AHREFS_BASE_URL}/management/projects"
    resp = _get_with_retry(url)
    if resp.status_code == 401:
        print("❌ Ahrefs authentication failed — check AHREFS_API_KEY.")
        sys.exit(1)
    if resp.status_code != 200:
        print(f"❌ Ahrefs /management/projects returned {resp.status_code}: {resp.text[:300]}")
        sys.exit(1)
    data = resp.json()
    if isinstance(data, list):
        return data
    for key in ("projects", "data"):
        if key in data:
            return data[key]
    print("❌ Unexpected response from /management/projects:")
    print(json.dumps(data, indent=2)[:1000])
    sys.exit(1)


def _load_excluded() -> set:
    if not os.path.exists(EXCLUDED_FILE):
        return set()
    excluded = set()
    with open(EXCLUDED_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                excluded.add(line.lower())
    return excluded


def _project_name(p: dict) -> str:
    return p.get("project_name") or p.get("name") or p.get("title") or p.get("url") or ""


def _project_domain(p: dict) -> str:
    raw = p.get("url") or p.get("target") or p.get("domain") or ""
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    domain = parsed.netloc or parsed.path
    return re.sub(r"^www\.", "", domain).strip("/")


def _filter_active(projects: list, excluded: set) -> list:
    return [
        p for p in projects
        if p.get("access") == "shared"
        and (p.get("keyword_count") or 0) > 0
        and _project_name(p).lower() not in excluded
    ]


# ── Client name matching (same as Striking Distance step4_assign.py) ──────────

def _load_aliases() -> dict:
    if not os.path.exists(ALIASES_FILE):
        return {}
    aliases = {}
    with open(ALIASES_FILE, newline="", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",", 1)
            if len(parts) == 2:
                aliases[parts[0].strip().lower()] = parts[1].strip().lower()
    return aliases


def _load_manual_assignments() -> dict:
    if not os.path.exists(MANUAL_ASSIGN_FILE):
        return {}
    manual = {}
    with open(MANUAL_ASSIGN_FILE, newline="", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Split on LAST comma so project names containing commas work correctly
            # e.g. "Diamond Legal, PC,Christian" → key="diamond legal, pc", value="Christian"
            parts = line.rsplit(",", 1)
            if len(parts) == 2:
                manual[parts[0].strip().lower()] = parts[1].strip()
    return manual


def _normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _resolve(client_name: str, exact_map: dict, norm_map: dict, aliases: dict = None) -> tuple:
    """Return (strategist, match_type). Mirrors Striking Distance step4_assign.py."""
    if aliases:
        sheet_name = aliases.get(client_name.lower())
        if sheet_name:
            strategist, _ = _resolve(sheet_name, exact_map, norm_map, None)
            if strategist != "Unassigned":
                return strategist, "alias"

    if client_name.lower() in exact_map:
        return exact_map[client_name.lower()], "exact"

    norm_key = _normalize(client_name)
    if norm_key in norm_map:
        return norm_map[norm_key], "normalized"

    for sheet_norm, strategist in norm_map.items():
        shorter, longer = sorted([norm_key, sheet_norm], key=len)
        if (len(shorter) >= 8
                and longer.startswith(shorter)
                and (len(shorter) == len(longer) or longer[len(shorter)] == " ")):
            return strategist, "prefix"

    close = get_close_matches(norm_key, norm_map.keys(), n=1, cutoff=0.80)
    if close:
        return norm_map[close[0]], "fuzzy"

    return "Unassigned", "unassigned"


def _fetch_strategist_mapping() -> dict:
    """Download Column A (client) and Column G (strategist) from STRATEGIST_SHEET_ID."""
    url = f"https://docs.google.com/spreadsheets/d/{config.STRATEGIST_SHEET_ID}/export?format=csv"
    try:
        resp = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  ⚠️  Could not fetch strategist sheet (HTTP {resp.status_code}). Clients will be Unassigned.")
            return {}
    except requests.RequestException as e:
        print(f"  ⚠️  Network error fetching strategist sheet: {e}. Clients will be Unassigned.")
        return {}

    mapping = {}
    client_col = strategist_col = None
    reader = csv.reader(io.StringIO(resp.text))
    for row in reader:
        if client_col is None:
            for j, cell in enumerate(row):
                if cell.strip() == "Client Name":
                    client_col = j
                if cell.strip() == "SEO Strategist":
                    strategist_col = j
            if client_col is not None and strategist_col is not None:
                continue
            continue
        if not row or len(row) <= max(client_col, strategist_col):
            continue
        client    = row[client_col].strip()
        strategist = row[strategist_col].strip()
        if client and strategist:
            mapping[client.lower()] = strategist
    return mapping


def _fetch_red_flag_clients() -> set:
    """
    Read the Classification Sheet (specific tab via gid).
    Returns set of lowercased client names where Column R == 'FLAGGED'.
    """
    url = (
        f"https://docs.google.com/spreadsheets/d/{config.STRATEGIST_SHEET_ID}"
        f"/export?format=csv&gid={config.CLASSIFICATION_SHEET_GID}"
    )
    try:
        resp = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  ⚠️  Could not fetch classification sheet (HTTP {resp.status_code}). No red flags loaded.")
            return set()
    except requests.RequestException as e:
        print(f"  ⚠️  Network error fetching classification sheet: {e}. No red flags loaded.")
        return set()

    red_flags = set()
    client_col = None
    reader = csv.reader(io.StringIO(resp.text))
    COL_R = 17  # 0-indexed column R

    for row in reader:
        # Auto-detect client name column from header row
        if client_col is None:
            for j, cell in enumerate(row):
                if "client" in cell.strip().lower():
                    client_col = j
                    break
            if client_col is None:
                client_col = 0  # fallback to column A
            continue

        if len(row) > COL_R and len(row) > client_col:
            client = row[client_col].strip()
            flag   = row[COL_R].strip().upper()
            if client and flag == "FLAGGED":
                red_flags.add(client.lower())

    return red_flags


def _clean_client_name(raw_name: str, aliases: dict) -> str:
    """Apply alias mapping to get clean client name, preserving original case from alias."""
    alias = aliases.get(raw_name.lower())
    if alias:
        return alias
    return raw_name


# ── Main entry point ───────────────────────────────────────────────────────────

def run() -> list:
    """
    Entry point for Step 1.
    Returns list[ClientRecord].
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 1 — Building active client list")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    excluded = _load_excluded()
    aliases  = _load_aliases()
    manual   = _load_manual_assignments()

    if excluded:
        print(f"  Excluding {len(excluded)} project(s): {', '.join(sorted(excluded))}")
    if aliases:
        print(f"  Loaded {len(aliases)} alias(es) from name_aliases.csv")
    if manual:
        print(f"  Loaded {len(manual)} manual strategist override(s)")

    # Fetch data sources
    all_projects = _fetch_ahrefs_projects()
    active = _filter_active(all_projects, excluded)
    print(f"  Found {len(active)} active Ahrefs project(s).\n")

    mapping  = _fetch_strategist_mapping()
    norm_map = {_normalize(k): v for k, v in mapping.items()}
    red_flags = _fetch_red_flag_clients()

    print(f"  Loaded {len(mapping)} client→strategist mapping(s).")
    print(f"  Loaded {len(red_flags)} red-flagged client(s).\n")

    clients = []
    match_log = []
    unassigned = set()

    for project in active:
        raw_name   = _project_name(project)
        domain     = _project_domain(project)
        clean_name = _clean_client_name(raw_name, aliases)

        # Strategist assignment
        override = manual.get(raw_name.lower())
        if override:
            strategist = override
        else:
            strategist, match_type = _resolve(clean_name, mapping, norm_map, aliases)
            if match_type in ("alias", "prefix", "fuzzy"):
                match_log.append((clean_name, match_type, strategist))
            if strategist == "Unassigned":
                unassigned.add(clean_name)

        # Red flag — check both clean name and raw name
        is_red = (
            clean_name.lower() in red_flags
            or raw_name.lower() in red_flags
        )

        clients.append(ClientRecord(
            project_name=raw_name,
            client_name=clean_name,
            domain=domain,
            strategist=strategist,
            is_red_flag=is_red,
        ))

    if match_log:
        seen = set()
        print("  Auto-matched client names (verify these are correct):")
        for name, mtype, strat in match_log:
            if name not in seen:
                print(f"    [{mtype}] '{name}' → {strat}")
                seen.add(name)

    if unassigned:
        print(f"\n  ⚠️  {len(unassigned)} client(s) could not be matched to a strategist:")
        for name in sorted(unassigned):
            print(f"    {name}")
        print("  To fix: add them to name_aliases.csv or manual_strategist_assignments.csv")

    red_count = sum(1 for c in clients if c.is_red_flag)
    print(
        f"\n  ✅ Step 1 complete — {len(clients)} client(s) | "
        f"{red_count} red-flagged | "
        f"{len(unassigned)} unassigned."
    )

    return clients
