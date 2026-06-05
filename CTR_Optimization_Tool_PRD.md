# PRD: CTR Optimization Tool — Title & Meta Rewrite Engine

## Project Summary

Build a tool that pulls GSC data across all client accounts, identifies pages with high impressions but low CTR, below the expected curve for their ranking position, generates title tag and meta description rewrite recommendations, and outputs everything into a per-client Google Sheet for VA execution.

This tool runs on demand. Each run produces two outputs: a local report saved to a `/reports` folder and a Google Sheet created in this Google Drive folder https://drive.google.com/drive/folders/18KlaH2hlGEXJs-9fk1e8R-_S0N-aoRoS which you should already know how to and have access to.

---

## Context for Claude Code

Before building anything, check the existing projects we've worked on under /Users/rod/Library/Mobile Documents/com~apple~CloudDocs/New Initiate Lift/My Customers/Constellation Marketing

- **GSC API setup** — We've connected to the Google Search Console API in previous projects. Find how authentication and data pulls are configured and reuse that pattern.
- **Google Sheets API setup** — We've written to Google Sheets in previous projects. Find the existing auth and write patterns and reuse them.
- **Client list and multi-site handling** — Some of our ~64 clients have multiple websites. Previous projects should have the client-to-site mapping. Find and reference it.
- **Anything else you need** let me know.
- **Standards** Also make sure to capture some of the standard requirements we've used repeateadily throughout other projects, common ones like gitignore, claude.md, readme, setup, etc etc etc.

Do not rebuild what already exists. Reuse existing configurations, auth flows, and client mappings.

---

## Data Sources

### 1. Google Search Console (via existing API setup)
Pull the following per page, per client property:
- Page URL
- Top query (highest impression query for that page)
- Impressions
- Clicks
- CTR
- Average position
- make any additional suggestions

**Date range:** Last 90 days (to get a stable baseline, not skewed by short-term fluctuations).

**Filters at pull:**
- Only pages with impressions ≥ 500 over the 90-day period (ignore low-traffic pages where CTR changes won't matter)
- Only pages in positions 4–15 (positions 1–3 are already performing; below 15 doesn't get enough visibility to meaningfully test)
- unless you feel these need adjusting

### 2. Client Classification Sheet
**URL:** https://docs.google.com/spreadsheets/d/1sX4Y9XhP4esV5PA_QSsro46rKDBKXDWMrKIA-85CGRo/edit?gid=584907407#gid=584907407

- **Column R** flags which clients are marked as "red" (at-risk clients)
- Use this to tag each page in the output so we can prioritize or filter by client status
- Pull client name and red-flag status at minimum

---

## Core Logic

### Step 1: Define the Expected CTR Curve

Use a standard CTR-by-position benchmark as the baseline curve. Suggested starting points:

| Position | Expected CTR |
|----------|-------------|
| 1        | 27–30%      |
| 2        | 15–17%      |
| 3        | 10–12%      |
| 4        | 7–8%        |
| 5        | 5–6%        |
| 6        | 4–5%        |
| 7        | 3–4%        |
| 8        | 2.5–3.5%    |
| 9        | 2–3%        |
| 10       | 2–2.5%      |
| 11–15    | 1–2%        |

**Better approach if feasible:** Calculate an internal CTR curve from the aggregate GSC data across all client accounts. This gives us a curve specific to legal/attorney SERPs rather than a generic industry average. If the data supports it, use the internal curve. If not, fall back to the benchmark table above.

### Step 2: Identify Below-Curve Pages

For each page in the dataset:
1. Look up the expected CTR for its average position (using the curve from Step 1).
2. Compare the page's actual CTR to the expected CTR.
3. Calculate the gap: `CTR_gap = expected_CTR - actual_CTR`
4. Flag pages where actual CTR is meaningfully below expected (suggested threshold: actual CTR is ≤ 70% of expected CTR for that position).

### Step 3: Generate Title & Meta Description Rewrites

Use an AI model API (Claude API) to generate rewrites for each flagged page. The prompt should instruct the model to:

**For title tags:**
- Keep the primary, compelling title within the first 55–60 characters (the visible portion in Google SERPs).
- **IMPORTANT — Extended title strategy:** After the primary title, extend the title tag beyond 60 characters to embed additional ranking signals. These extra characters won't display in search results but Google still indexes and uses them for ranking. Use this extra space for:
  - Related/LSI keywords relevant to the page's practice area
  - Geo modifiers (city, state, region) if the page targets a local market
  - Secondary practice area terms that support the primary topic
  - Example: `Experienced Personal Injury Lawyer | Free Consultation | [City] Car Accident Attorney, Slip and Fall Claims, [State]`
  - The visible portion (`Experienced Personal Injury Lawyer | Free Consultation`) is the hook. Everything after is bonus ranking signal.

**For meta descriptions:**
- 150–160 characters
- Include the target query naturally
- Include a clear call to action (free consultation, call now, etc.)
- Mention differentiators where possible (years of experience, case results, local presence)

**Prompt inputs per page:**
- Current title tag
- Current meta description
- Target query (highest impression query)
- Page URL (for context on practice area)
- Current position and CTR
- Client name (for brand inclusion if appropriate)

**Prompt output per page:**
- Recommended new title tag (with extended portion clearly marked)
- Recommended new meta description
- Brief rationale (1 sentence explaining the rewrite strategy)

---

## Output Specifications

Each run produces TWO outputs:

### Output 1: Local Report
- **Location:** `/reports/` folder in the project directory
- **Format:** CSV or JSON (whichever is more practical for archival/re-processing)
- **Filename pattern:** `ctr_rewrite_report_YYYY-MM-DD.csv`
- **Contents:** Full dataset — every flagged page with all columns (client, URL, query, current title, current meta, current CTR, expected CTR, CTR gap, recommended title, recommended meta, rationale, client red-flag status)

### Output 2: Google Sheet
- **Location:** Create in this Drive folder: https://drive.google.com/drive/folders/18KlaH2hlGEXJs-9fk1e8R-_S0N-aoRoS
- **Sheet name:** `CTR Rewrite Recommendations — YYYY-MM-DD`
- **Structure:** One tab per client. Each tab named with the client name.
- **Columns per tab:**

| Column | Description |
|--------|-------------|
| Page URL | The URL being optimized |
| Target Query | Highest impression query for this page |
| Current Position | Average position over 90-day period |
| Current CTR | Actual CTR over 90-day period |
| Expected CTR | What the CTR should be based on position curve |
| CTR Gap | How far below expected (percentage points) |
| Current Title Tag | Existing title tag |
| Recommended Title Tag | AI-generated rewrite (extended version) |
| Title Tag Character Count | Character count of recommended title |
| Current Meta Description | Existing meta description |
| Recommended Meta Description | AI-generated rewrite |
| Rationale | 1-sentence explanation of the rewrite strategy |
| Client Status | Red flag or normal |
| Baseline Logged | Yes/No — for tracking whether this row has been logged in the testing sheet |

- **Formatting:**
  - Header row frozen and bolded
  - Red-flagged client tabs should have a visual indicator (red tab color or red header background)
  - Sort pages within each tab by CTR gap descending (worst underperformers first)

---

## SEO Testing Sheet

There is no existing testing sheet. This tool needs to create or populate one as part of the output process.

**Option A (simpler):** Add a "Baseline Log" tab to the same Google Sheet output. This tab contains one row per page across all clients with:
- Client name
- Page URL
- Target query
- Baseline CTR (at time of analysis)
- Baseline position (at time of analysis)
- Date of analysis
- Date changes were deployed (blank — VA fills in)
- Measurement date (auto-set to 14 days after analysis date)
- Post-change CTR (blank — filled in at measurement)
- Post-change position (blank — filled in at measurement)

**Option B:** Create this as a separate sheet. Rod to decide.

Default to Option A unless told otherwise.

---

## Technical Notes

- **Rate limiting:** GSC API has daily query limits. If pulling 64+ client properties, implement batching with appropriate delays. Check how previous projects handled this.
- **Error handling:** If a client property returns no data or the API errors out, log it and continue. Don't let one failed client kill the whole run.
- **Title tag extraction:** The tool needs to get current title tags from live pages. This likely requires either crawl data or fetching each page's `<title>` tag. Determine the most efficient approach — if there's a crawl database or Screaming Frog export from previous projects, use that. Otherwise, fetch live pages in batches.
- **Meta description extraction:** Same as above — pull from live pages or existing crawl data.
- **AI API calls:** Batch rewrite generation efficiently. Group pages by practice area or client to maintain context in prompts. Implement retry logic for API failures.

---

## What Success Looks Like

By Friday 2026-06-05:
1. The tool runs end-to-end without manual intervention.
2. Local report is saved to `/reports/`.
3. Google Sheet is created in the specified Drive folder with per-client tabs.
4. Every flagged page has a recommended title and meta description rewrite.
5. Baseline data is logged and ready for measurement.
6. The output is clean enough to hand directly to a VA for execution without Rod needing to manually edit it.

---

## Out of Scope (for this sprint)

- Deploying the changes (VA handles this)
- Building a re-measurement tool (separate future project)
- Analyzing non-title/meta factors affecting CTR
- Handling pages outside positions 4–15
- Competitor SERP title analysis (nice to have but not required for v1)
