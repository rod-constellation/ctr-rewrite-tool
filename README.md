# CTR Optimization Tool — Title & Meta Rewrite Engine

Identifies pages across all Constellation Marketing client accounts that rank in Google
but are getting fewer clicks than expected for their position. Generates AI-powered title
tag and meta description rewrites for VA execution.

---

## What It Does

1. Pulls all active clients from Ahrefs rank tracker
2. Fetches 90 days of Google Search Console page data — canonical pages only (cannibalization filtered)
3. Builds an internal CTR curve and flags service pages underperforming at ≤70% of expected CTR
4. Fetches current title/meta via DataForSEO SERP (Cloudflare-proof, 2-pass lookup)
   + competitor context for the top 5 positions
5. Generates rewrites using Kimi K2 via OpenRouter — 7 rules, 3-section extended tail,
   secondary queries from GSC as raw material for the tail
6. Outputs a local CSV and a per-strategist Google Sheet with homepage approval tab

---

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Set up credentials

```bash
cp .env.example .env
```

| Variable | Where to find it |
|----------|-----------------|
| `GOOGLE_CLIENT_ID` | Striking Distance Keywords Tactic/.env |
| `GOOGLE_CLIENT_SECRET` | Striking Distance Keywords Tactic/.env |
| `GOOGLE_REFRESH_TOKEN` | Striking Distance Keywords Tactic/.env |
| `GOOGLE_SHEETS_REFRESH_TOKEN` | Striking Distance Keywords Tactic/.env |
| `AHREFS_API_KEY` | Root Claude Code Constellation/.env |
| `OPENROUTER_API_KEY` | Striking Distance Keywords Tactic/.env |
| `DATAFORSEO_LOGIN` | spr0/.env |
| `DATAFORSEO_PASSWORD` | spr0/.env |

Regenerate OAuth tokens if expired:
```bash
python3 setup_auth.py          # agency account (GSC access)
python3 setup_auth.py --sheets # personal account (Drive/Sheets)
```

---

## Running

```bash
# Preview — shows what would be flagged, no AI calls, no files written
python3 main.py --dry-run

# Full run
python3 main.py

# Resume from a step if interrupted
python3 main.py --from-step 4

# Skip DataForSEO SERP (faster, no competitor context or current title lookup)
python3 main.py --skip-serp

# Analyze title patterns before running rewrites
python3 analyze_titles.py --sample 40
python3 analyze_titles.py --client "Dressie Law Firm"
```

---

## Output

### Local report
`reports/ctr_rewrite_report_YYYY-MM-DD.csv` (auto-versioned: `_B.csv`, `_C.csv` etc. for re-runs)

### Google Sheet
Created in the configured Drive folder. Auto-versioned name.

| Tab | Contents |
|-----|---------|
| **MASTER** | All flagged service pages, sorted by CTR gap (worst first) |
| **Per-strategist** | Their clients' pages only. Red-flagged rows highlighted. |
| **`* Needs Client Approval *`** | Homepages only. Yellow tab. Requires client sign-off before changes. |
| **Baseline Log** | Pre-populated for VA tracking — deploy date + measurement date (analysis + 14 days) |

---

## Adjusting Scope

Edit `config.py`:

```python
GSC_MIN_POSITION    = 5     # lower to include higher-ranking pages
GSC_MAX_POSITION    = 12    # raise to 15 or 20 for deeper positions
GSC_MIN_IMPRESSIONS = 500   # lower to include more low-traffic pages
CTR_THRESHOLD_RATIO = 0.70  # 0.80 = more pages flagged, 0.60 = fewer
GSC_LOOKBACK_DAYS   = 90    # change to 60 or 30 for shorter data window
GSC_SECONDARY_QUERIES_COUNT   = 8   # secondary queries kept per page for tail
GSC_SECONDARY_MIN_IMPRESSIONS = 30  # min impressions for a secondary query to qualify

# File types excluded before classification (can't update title/meta via CMS)
EXCLUDED_URL_EXTENSIONS = [".pdf", ".doc", ".docx", ".pptx", ...]  # edit to add/remove
```

---

## Managing Trust Words

Trust words are used in title tags when no confirmed CTA exists.
Edit `config/trust_words.txt` — no code changes needed.

The file documents safe words, conditional words (need verification), and restricted words
(prohibited by state bar advertising rules in FL, TX, NJ, NY, CA and most ABA-model states).
Never activate "expert," "specialist," "best," "top," or "#1" without verifying the specific
state's bar advertising rules for each client.

---

## Adding/Excluding Clients

**Exclude a client:** Add their Ahrefs project name to `excluded_clients.txt`

**Fix a name mismatch:** Add to `name_aliases.csv`:
```
AhrefsProjectName, Google Sheet Client Name
```

**Override strategist assignment:** Add to `manual_strategist_assignments.csv`:
```
AhrefsProjectName,StrategistName
```

---

## The Rewrite Algorithm

See [ALGORITHM.md](ALGORITHM.md) for the full logic including:
- How the CTR curve is built and what the 70% threshold means
- All 7 title tag rules (language, verbatim query, CTA confirmation, no brand, one city, synonyms, topical coherence)
- The 3-section extended tail structure (trust phrase → secondary queries → LSI gap-fill)
- Geo repetition rule (city max 2× total, state once, then geo-free)
- URL city extraction (URL slug overrides query city for geo targeting)
- Meta description formula including where the brand name belongs

---

## Estimated Runtime & Cost

| Step | Time |
|------|------|
| Step 1 (Ahrefs) | ~1–2 min |
| Step 2 (GSC) | ~10–20 min for 50+ clients |
| Step 3 (classify) | < 1 sec |
| Step 4 (SERP lookup) | ~10–15 min |
| Step 5 (AI rewrites) | ~5–10 min for ~40 pages |
| Step 6 (output) | ~2–3 min |

**API costs per full run:**
- DataForSEO SERP: ~$1–3
- OpenRouter/Kimi K2: ~$1–5
- All other APIs: included in existing subscriptions
