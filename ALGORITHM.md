# CTR Optimization Algorithm — Title & Meta Rewrite Engine

This document describes the classification and rewrite logic as a portable reference.
The same principles can be applied manually, in other tools, or by VAs.

---

## Phase 1 — Identify Underperforming Service Pages

### 1.1 Data Collection

**Source:** Google Search Console (90-day window per property)
**Scope filter applied in Step 2:**
- Impressions ≥ 500
- Average position between 5 and 12 (the "money zone")
- Both limits configurable in `config.py`

**Per page, we collect:**
- Page URL, top query (highest impressions), total impressions/clicks, CTR, avg position
- **Secondary queries** — all other queries the page ranks for (sorted by impressions, up to 8 per page). These are the raw material for the extended title tail.

---

### 1.2 Service Page Filter

Only pages with **transactional/commercial intent** proceed to the rewrite step.

**Passes as service page if:**
1. Top query contains hire-intent keywords: `attorney`, `lawyer`, `law firm`, `legal services`, `law office`, `counsel`, etc.
2. OR top query contains implied hire-intent practice area terms: `DUI`, `car accident`, `personal injury`, `criminal defense`, `divorce`, etc.

**Hard excluded (informational/blog) if:**
- URL contains: `/blog/`, `/news/`, `/article`, `/resources/`, `/faq/`, `/guide/`, etc.

**Hard excluded (non-editable file types) — filtered in Step 2:**
- URL ends in: `.pdf`, `.doc`, `.docx`, `.pptx`, `.ppt`, `.xls`, `.xlsx`, `.odt`, `.odp`, `.ods`, `.rtf`, `.txt`
- Title/meta can't be updated via CMS for these — the file itself would need to be edited
- Configurable via `EXCLUDED_URL_EXTENSIONS` in `config.py`

**Homepages** (URL with no meaningful path) are separated into a `* Needs Client Approval *` tab — title tag changes to the homepage require explicit client sign-off before implementation.

---

### 1.3 CTR Benchmark Curve

**Internal curve (preferred):**
- Group all candidate pages by `floor(position)` → compute median CTR per bucket
- Used when bucket has ≥ 30 pages

**Fallback benchmarks:**

| Position | Expected CTR |
|----------|-------------|
| 5  | 5.5%  |
| 6  | 4.5%  |
| 7  | 3.5%  |
| 8  | 3.0%  |
| 9  | 2.5%  |
| 10 | 2.25% |
| 11 | 1.75% |
| 12 | 1.75% |

**Flag condition:** `actual_CTR ≤ 70% × expected_CTR`

**CTR Gap** = `expected_CTR − actual_CTR`. Pages sorted by gap descending (worst first).

**Config dial:** `CTR_THRESHOLD_RATIO = 0.70` in `config.py`

---

## Phase 2 — Gather Context for Rewrites

1. **Current title/meta** — Two-pass SERP lookup via DataForSEO (bypasses Cloudflare):
   - Pass 1: Fetch top-query SERP at depth 15. If the client's page appears in positions 1–15, extract its title/meta from there.
   - Pass 2 (fallback): `site:URL` query to force Google to surface the specific page.
   - Result: what Google currently shows, which IS the correct baseline for CTR comparison.

2. **Competitor titles/metas** — Top 5 organic results from the same SERP (not the client's own page).

3. **Secondary queries** — Pulled from GSC data in Step 2 (up to 8 per page, sorted by impressions). These are the primary source for the extended tail — real proven-relevant queries the page already ranks for.

---

## Phase 3 — Rewrite Logic (7 Rules + 3-Section Structure)

### The Seven Rules

**Rule 1 — Language match:**
If the URL contains `/es/`, `/fr/`, `/pt/`, etc. or the current title is non-English,
write the entire recommendation in that language.

**Rule 2 — Top query verbatim in visible title (with geo exception):**
The SERVICE/PRACTICE AREA terms from the top query must appear verbatim in the visible portion.
GEO EXCEPTION: If the URL slug contains a city name (e.g., `/santa-clara-criminal-lawyer/`),
that city is the authoritative target — use it in the title even if the top query mentions
a different city. URL city always overrides query city.

**Rule 3 — CTA only if confirmed:**
Only add a CTA ("Free Consultation," "Free Case Review," "Available 24/7," etc.) if it
appears in the firm's existing title or meta. Never invent one.
If no CTA in current content → use a trust phrase from the approved list instead (Rule 3A).

**Rule 4 — No brand name anywhere:**
No firm name in the title tag — not in the visible portion, not in the extended tail.
Brand belongs in the meta description, not the title.

**Rule 5 — One city, no counties:**
Use the primary city (from URL slug or top query) at most twice in the entire title.
Use the state name once. No county names (cannibalization risk with county-targeted pages).
No multiple distinct cities.

**Rule 6 — Lawyer/attorney synonym variation:**
If visible uses "lawyer," the tail must include an "attorney" variation, and vice versa.

**Rule 7 — Topical coherence:**
The entire title must stay within the page's single practice area. No mixing topics.

---

### Title Tag: Visible Portion (characters 1–60)

Format: `[Top query service terms + URL city] | [CTA if confirmed]`

- Must include the top query's service/practice area terms verbatim (minimal title-casing only)
- Use the URL city, not the query city if they differ
- Only add a CTA if confirmed in existing content
- Never place a separator (`|`, `-`) immediately after `?`, `!`, `.`
- Hard cap: 60 characters
- No brand name

---

### Title Tag: Extended Tail (characters 61+, indexed by Google, invisible to searchers)

Built in three sections:

**Section A — Trust phrase** (only when no confirmed CTA fills this slot):
One short phrase (3–5 words) using ONLY words from `config/trust_words.txt`.
Matched to practice area: `Experienced DUI Defense Attorneys`, `Trusted Injury Lawyers`, etc.

**Section B — Secondary queries from GSC:**
Include the most relevant secondary queries verbatim or with minimal modification.
- Always include the lawyer/attorney synonym (Rule 6)
- City max 2 times total across the WHOLE title (once in visible + once here)
- After the two city uses: state name once, then pure keyword phrases with NO geo
- No counties, no brand name, stay in one practice area

**GEO REPETITION RULE:**
City appears ≤ 2 times across the entire title. After that, state once, then geo-free terms.
`DUI Lawyer Athens GA | Experienced Athens DUI Attorneys | Georgia DUI Defense - Drunk Driving Lawyer - Felony DUI` ✅
`DUI Lawyer Athens GA | Athens DUI Attorneys - Athens Georgia DUI Lawyers - Athens DUI Attorney` ❌

**Section C — LSI gap-fill** (1–2 terms max, only if genuine gaps exist):
Semantically related terms NOT already in the secondary queries.
Examples: "DWI" on a DUI page, "auto accident" on a "car accident" page, practice-area sub-topics.
Skip if no genuine gap exists — do not pad.

**Format rules:**
- Keyword phrases only (no questions, sentences, or punctuation marks)
- Sections separated by pipes (`|`); terms within sections by dashes (`-`)
- Total tail target: 100–160 characters (total title: 140–220 chars)

---

### Meta Description (150–160 characters)

- Open by addressing the searcher's situation
- Include the top search query naturally in the first half
- Add ONE differentiator (city, practice area, experience signal)
- Mirror the confirmed CTA if one exists; otherwise end with a neutral action phrase
- Include the firm name naturally (mid-sentence or end) — brand belongs here, not in the title
- Do NOT start with the firm name
- Target 155 characters exactly

---

## Configuration Reference

| Setting | Default | Effect |
|---------|---------|--------|
| `GSC_MIN_POSITION` | 5 | Lower to include higher-ranking pages |
| `GSC_MAX_POSITION` | 12 | Raise to 15 or 20 for deeper positions |
| `GSC_MIN_IMPRESSIONS` | 500 | Lower to include more low-traffic pages |
| `GSC_LOOKBACK_DAYS` | 90 | Shorten for faster signal, extend for stability |
| `CTR_THRESHOLD_RATIO` | 0.70 | Raise for more pages flagged, lower for fewer |
| `GSC_SECONDARY_QUERIES_COUNT` | 8 | Secondary queries kept per page for the tail |
| `GSC_SECONDARY_MIN_IMPRESSIONS` | 30 | Min impressions to include a secondary query |
| `AI_MODEL` | moonshotai/kimi-k2 | OpenRouter model for rewrites |
| `AI_BATCH_SIZE` | 10 | Pages per AI API call |
| `SERP_FETCH_DEPTH` | 15 | SERP depth for finding client's own page |
| `SERP_RESULT_COUNT` | 5 | Competitor positions to include in AI prompt |

**Trust words** are maintained in `config/trust_words.txt` — edit to add/remove without touching code. Includes documented state advertising restrictions for words like "expert," "specialist," "best."
