# CLAUDE.md — CTR Optimization Tool

## Purpose

This tool identifies service/transactional pages across all active Constellation Marketing
client accounts that rank positions 5–12 but are getting significantly fewer clicks than
similar pages at the same position. It generates AI title tag and meta description rewrites
and outputs them to a per-strategist Google Sheet for VA execution.

**Key distinctions:**
- Only service pages with transactional/commercial search intent are rewritten
- Blog posts, FAQ pages, and informational articles are filtered out
- Homepages require explicit client approval (separate tab, not deployed by VAs)

---

## How It Works (6 steps)

**step1_clients.py** — Pull active clients from Ahrefs ("Active Clients" folder, `access=shared`).
Map each to a strategist via `name_aliases.csv` + Google Sheet lookup.
Read red-flag status from Classification Sheet (Column R == "FLAGGED").

**step2_gsc.py** — For each client domain, match to a GSC property and pull 90-day
page+query analytics. Aggregates to page level, filters to positions 5–12 with ≥500 impressions.
Also applies a **query ownership filter** — if a page's top query is "owned" by a different
page on the same domain (more impressions for that query), the page is dropped as a
secondary/cannibalized page. Only canonical pages proceed.
Extracts **secondary queries** (up to 8 per page, ≥30 impressions each) for the extended tail.

**step3_classify.py** — Two-stage classification:
1. Build internal CTR curve (median per position bucket) from aggregate data
2. Flag pages where actual CTR ≤ 70% of expected CTR
3. Filter to service pages only: query has hire-intent signals AND URL doesn't have blog patterns
4. Sort flagged pages by CTR gap descending (worst underperformers first)

**step4_fetch_meta.py** — Two-pass SERP lookup per page (DataForSEO — bypasses Cloudflare):
- Pass 1: Fetch top-query SERP at depth 15. Look for the client's own URL in results.
  Same call provides top 5 competitor titles/metas for AI context.
- Pass 2 (fallback): `site:URL` query for pages not found in Pass 1.

**step5_rewrite.py** — Batches pages by client, calls OpenRouter (Kimi K2).
Per-page inputs: URL (city extracted from slug), top query, position, CTR, confirmed CTA
from existing content, secondary queries from GSC, competitor SERP context.
AI generates: recommended_title (3-section extended tail), recommended_meta, rationale.

**step6_output.py** — Writes local CSV to `/reports/` and creates a versioned Google Sheet:
- MASTER tab + per-strategist tabs + Baseline Log tab
- Homepages → `* Needs Client Approval *` tab (yellow, excluded from strategist workflow)
- Sheet auto-versioned: first run = date only, subsequent = B, C, D...

---

## Running the Tool

```bash
# Preview — shows client/page counts, no AI calls, no files written
python3 main.py --dry-run

# Full run
python3 main.py

# Resume from a specific step using checkpoint
python3 main.py --from-step 4

# Skip DataForSEO SERP fetching
python3 main.py --skip-serp
```

**Analysis only (run before rewrites to understand title patterns):**
```bash
python3 analyze_titles.py --sample 40
python3 analyze_titles.py --client "Dressie Law Firm"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `config.py` | All configuration — thresholds, service page keywords, Google IDs |
| `config/trust_words.txt` | Approved trust words for titles — edit to add/remove, no code changes needed |
| `models.py` | Data classes: ClientRecord, PageOpportunity, CompetitorResult |
| `ALGORITHM.md` | Full documentation of classify + rewrite logic (all 7 rules) |
| `analyze_titles.py` | Standalone analysis script — run before rewrites to see patterns |
| `excluded_clients.txt` | Ahrefs projects to skip (one per line, # comments) |
| `name_aliases.csv` | Maps Ahrefs project names to clean client names |
| `manual_strategist_assignments.csv` | Hard-override Ahrefs project → strategist |
| `.checkpoint.json` | Auto-created; allows resuming interrupted runs |

---

## Adjusting the Scope

All tunable parameters in `config.py` have inline comments:

```python
# GSC filters
GSC_MIN_POSITION    = 5     # lower to include top-ranking pages
GSC_MAX_POSITION    = 12    # raise to 15 or 20 for deeper positions
GSC_MIN_IMPRESSIONS = 500   # lower for more low-traffic pages

# CTR threshold
CTR_THRESHOLD_RATIO = 0.70  # raise to flag more, lower for fewer

# Secondary queries for extended tail
GSC_SECONDARY_QUERIES_COUNT   = 8   # how many secondary queries to keep per page
GSC_SECONDARY_MIN_IMPRESSIONS = 30  # ignore very low-impression queries

# Service page detection
SERVICE_QUERY_KEYWORDS   = [...]   # hire-intent signals in the query
BLOG_URL_PATTERNS        = [...]   # URL patterns that indicate informational content
EXCLUDED_URL_EXTENSIONS  = [...]   # file types filtered before classification (.pdf, .docx, etc.)
```

---

## Managing Trust Words

Trust words are used in title tags when no confirmed CTA exists. They fill the same
"hook" role as a CTA without making a specific service promise.

Edit `config/trust_words.txt` directly — no code changes needed. The file documents:
- **Safe words**: trusted, experienced, dedicated, skilled, local, etc.
- **Conditional**: award-winning, board-certified (only if verifiable)
- **Restricted**: expert, specialist, best, top, #1 — prohibited in multiple states
  under bar advertising rules (FL, TX, NJ, NY, CA + most ABA-model states)

---

## The Title Rewrite Strategy (summary)

**7 rules applied to every title:**
1. Language match — Spanish page gets Spanish title
2. Top query verbatim — service terms from query; city from URL slug (overrides query city)
3. CTA only if confirmed in existing content — never invented
4. No brand name anywhere in title (brand goes in meta description instead)
5. One city, no counties — city max 2× total; state once; then geo-free terms
6. Lawyer/attorney synonym in the tail
7. Stay within one practice area — no mixing topics

**Extended tail: 3 sections:**
- Section A: Trust phrase (only if no CTA) from `config/trust_words.txt`
- Section B: Secondary queries from GSC (stripped of city repetition after 2 uses)
- Section C: 1–2 LSI gap-fill terms not already in secondary queries

Full details in `ALGORITHM.md`.

---

## Auth / Credentials

All credentials in `.env` (gitignored). Copy from:
- `GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN`, `OPENROUTER_API_KEY`, `AHREFS_API_KEY`
  → Striking Distance Keywords Tactic/.env
- `GOOGLE_SHEETS_REFRESH_TOKEN` → Striking Distance Keywords Tactic/.env
- `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` → spr0/.env

Run `python3 setup_auth.py` to regenerate Google OAuth tokens if expired.

---

## Output Sheet Structure

- **MASTER tab** — All flagged service pages, sorted by CTR gap descending
- **Per-strategist tabs** — Their assigned clients' pages only. Red-flagged rows highlighted.
- **`* Needs Client Approval *` tab** — Homepages only. Yellow tab. Requires explicit client
  approval before any changes are made.
- **Baseline Log tab** — One row per page for VA tracking (regular pages only).
  Measurement date = analysis + 14 days. VA fills in: deploy date, post-change CTR/position.

Sheet names are auto-versioned: `CTR Rewrite Recommendations — 2026-06-04` →
`...2026-06-04 B` → `...2026-06-04 C` etc. for re-runs on the same day.

---

## Important Notes for Claude

- Do NOT rebuild Google OAuth — reuse exact patterns from this project's `config.py`
- Do NOT commit `.env` or `reports/` (both gitignored)
- All CTR thresholds and position filters are in `config.py` — change there, not in step files
- The service page filter uses `config.SERVICE_QUERY_KEYWORDS` and `config.BLOG_URL_PATTERNS`
- Trust words are in `config/trust_words.txt` — edit there, not in the prompt
- When the AI prompt needs updating, edit `_SYSTEM_PROMPT_TEMPLATE` in `step5_rewrite.py`
- The trust words are injected into the prompt at runtime via `_build_system_prompt()`
