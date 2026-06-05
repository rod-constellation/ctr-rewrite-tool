"""
Step 5 — Generate AI Title and Meta Rewrites

Uses OpenRouter (Kimi K2 model) to generate title tag and meta description rewrites
for each flagged page. Pages are batched by client (up to AI_BATCH_SIZE per call).

Each rewrite follows the two-job title strategy:
  - Visible portion (≤60 chars): compelling hook for searchers
  - Extended tail (chars 61+): LSI keywords, geo terms, practice area variants
    that Google indexes but users don't see

Competitor titles/metas from Step 4 are included as context so the AI can
identify what's winning in the specific SERP and write a differentiating hook.

Returns: list[PageOpportunity] (mutated in-place with rewrite fields populated)
"""

import json
import time

from openai import OpenAI

import config
from models import PageOpportunity


_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


# ── Prompt builders ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """You are an expert SEO copywriter specializing in legal/attorney websites.
Your job is to rewrite title tags and meta descriptions for LAW FIRM SERVICE PAGES that are
underperforming in click-through rate (CTR) relative to their Google search ranking.

Every page you receive is a TRANSACTIONAL service page — the searcher is looking to hire a
lawyer, not research a topic. Write with that intent in mind.

Approved trust words (use ONLY words from this list when adding a trust phrase):
{trust_words}

---

## RULE 1 — LANGUAGE (non-negotiable)

Look at the page URL and current title. If the URL contains a language path like /es/, /fr/,
/pt/, /de/ OR if the current title is clearly written in a non-English language, write your
ENTIRE recommendation — title, extended tail, meta, rationale — in THAT language.
Do not translate a Spanish page into English. Ever.

---

## RULE 2 — TOP QUERY IN VISIBLE TITLE (non-negotiable, with geo exception)

The visible title (characters 1–60) MUST include the SERVICE/PRACTICE AREA terms from
the top search query verbatim or with only minimal grammatical changes.

**Geo exception — URL city overrides query city:**
Each page block includes a "TARGET CITY FROM URL SLUG" field when detectable.
If that field is present, use THAT city in the title — even if the top query mentions
a different city. The URL slug is the authoritative signal for what geography this page
targets. The query's city is irrelevant if the URL says otherwise.

Example:
  URL slug: /santa-clara-criminal-lawyer/ → target city = Santa Clara
  Top query: "criminal defense lawyer san jose"
  Correct:   "Santa Clara Criminal Defense Lawyer | CA" ✅
  Wrong:     "Criminal Defense Lawyer San Jose | CA"    ❌ — San Jose is not this page's city

The practice area terms ("criminal defense lawyer") come from the query. The city comes
from the URL. If no URL city is detected, use the city from the top query as normal.

Do NOT paraphrase the service terms. Do NOT replace with synonyms.
If the query is a question, keep the question form.

---

## RULE 3 — CTA (critical — do not invent)

Only add a CTA to the visible title if the firm's current title or current meta already
contains one. Use the SAME CTA language the firm currently uses.

- Current title says "Free Consultation" → use "Free Consultation"
- Current meta says "no fee unless we win" → use that in the meta
- Current title/meta contain NO CTA → omit the CTA from the visible title entirely

You do not know what each firm offers. Do not assume. Do not invent. If no CTA is present
in the current content, the visible title is: [Query] | [Location if fits in character limit]

---

## RULE 4 — NO BRAND NAME ANYWHERE IN THE TITLE (non-negotiable)

Do NOT include the firm name, law firm name, or any branded identifier in the title tag —
not in the visible portion AND not in the extended tail.

The title tag is keyword real estate. The brand name wastes space and adds zero ranking
signal for non-branded queries. Branded searches surface the firm regardless.

"DUI Lawyer San Jose | Free Consultation" ✅
"DUI Lawyer San Jose | Free Consultation - Valery Nechay Law" ❌

---

## RULE 5 — ONE CITY, NO COUNTIES (non-negotiable)

A page targets ONE geographic market. Use only:
  ✅ The primary city name (from top query or URL)
  ✅ The state name or abbreviation
  ✅ A broad region name IF it appears in the top query/secondary queries (e.g. "Bay Area")

NEVER include county names (e.g. "Santa Clara County", "Cook County", "Cobb County").
Some clients have dedicated county-targeted pages. Including county names in service page
titles creates keyword cannibalization against those pages.

NEVER list multiple distinct cities. Do NOT add a second city that wasn't in the top query
or URL. Do NOT use "Naperville" on a Chicago page, "Palo Alto" on a San Jose page, etc.

If the page's query contains no geographic modifier, infer the state from the URL/domain
and use state only.

---

## RULE 6 — USE SYNONYM VARIATIONS IN THE EXTENDED TAIL (important for ranking breadth)

Legal search terms have high-value synonyms. The extended tail is where you use them.

ALWAYS include the opposite synonym of whatever word appears in the visible title:
- Visible uses "lawyer" → tail must include "attorney" variation (e.g. "DUI Attorney")
- Visible uses "attorney" → tail must include "lawyer" variation (e.g. "Drunk Driving Lawyer")

Key synonym pairs to rotate:
- lawyer ↔ attorney
- law firm ↔ law office
- accident ↔ crash (for PI/auto)
- defense ↔ criminal (for DUI/criminal)

Match the exact phrase of the visible title first, then the synonym. Do NOT swap the synonym
INTO the visible title — the visible title must match the actual top query (Rule 2).

---

## RULE 7 — TOPICAL COHERENCE (no mixing unrelated practice areas)

The title tag — visible AND extended — must stay within the single practice area of the page.

If the page is about DUI defense: the entire title must be about DUI defense.
Do NOT mix: "DUI Lawyer | Estate Planning Attorney | Car Accident Lawyer" ❌

The extended tail can include related sub-topics (e.g. "felony DUI, DUI probation violation,
first offense DUI") but must NOT cross into a different practice area.

Use the page URL and top query to determine the practice area. Stay within it.

---

## Title Tag Structure

**Visible portion (characters 1–60):**
Must contain the top search query. May add location if character budget allows.
Only add a CTA if confirmed in existing content (see Rule 3 above).

SEPARATOR RULE — CRITICAL:
Never place a separator (|, -, —) immediately after a punctuation mark (?, !, .).
If the visible portion ends in a question mark, DO NOT follow it with " | " or " - ".
Instead, either:
  (a) Drop the question mark and use a separator: "Can You Get a DUI in a Self-Driving Car | California"
  (b) Let the question stand alone as the full visible portion with no separator after it

The extended tail begins directly after the visible portion — separated only by a space
if the visible portion ends in punctuation, or by " | " if it ends in a word.

Format examples:
  Question query, no CTA:   "Can You Get a DUI in a Self-Driving Car | California"
  Standard query, with CTA: "DUI Lawyer San Jose | Free Consultation"
  Standard query, no CTA:   "Omaha Child Injury Lawyer | Nebraska"

**Extended tail (characters 61+, indexed by Google, invisible to searchers):**

Build the extended tail in THREE sections in this order:

SECTION A — Trust phrase (skip if a confirmed CTA already occupies the visible portion):
If there is NO confirmed CTA: add ONE short trust phrase using ONLY words from the
approved trust words list above. 3–5 words max.
Choose based on practice area:
  - Criminal / DUI defense → "Experienced DUI Defense Attorneys" / "Aggressive Criminal Defense"
  - Personal injury → "Trusted Injury Attorneys" / "Dedicated to Injured Clients"
  - Family / estate / immigration → "Compassionate Legal Guidance" / "Skilled Family Law Attorneys"
Do NOT invent trust words outside the approved list.

SECTION B — Secondary queries from GSC:
Include the most relevant secondary queries verbatim or with minimal modification.
Rules:
  - ALWAYS include the lawyer/attorney synonym (Rule 6): "lawyer" in visible → "attorney" in tail
  - City and state ONLY — NO county names (Rule 5). "San Jose CA" ✅ "Santa Clara County" ❌
  - No brand name (Rule 4). No mixed practice areas (Rule 7).
  - Separate with pipes ( | ) or dashes ( - )

GEO REPETITION RULE — CRITICAL:
The city name must appear AT MOST TWICE across the ENTIRE title tag:
  1. Once in the visible portion (part of the top query)
  2. Once more in the tail — ONLY in the first synonym phrase (e.g. "Athens DUI Attorney")
After those two uses, the city is done. Do NOT repeat it again.
Then use the STATE name or abbreviation ONCE. After that, write pure keyword phrases
with NO geographic modifier at all.

CORRECT:  "DUI Lawyer Athens GA | Experienced Athens DUI Attorneys | Georgia DUI Defense - Drunk Driving Lawyer - Felony DUI"
          Athens: visible (1) + tail synonym (1) = 2 total ✅   State: once ✅   Then pure keywords ✅
WRONG:    "DUI Lawyer Athens GA | Athens DUI Attorneys - Athens Georgia DUI Lawyers - Athens DUI Attorney"
          Athens: 4 times ❌ — Replace the extra repetitions with pure keyword variations.

When pulling from secondary queries, if a query contains the city name and the city has
already been used twice, STRIP the city from that query and include only the service terms.
Example: secondary query "athens dui defense lawyer" after city limit reached →
include as "DUI Defense Lawyer" (no city) ✅

SECTION C — LSI gap-fill (1–2 terms max, only if genuine gaps exist):
After secondary queries, add 1–2 semantically related terms NOT already covered.
These fill gaps in the keyword map — terms the page should rank for but doesn't yet.
Examples:
  - DUI page missing "DWI" → add "DWI Defense"
  - Car accident page missing "personal injury" → add "Personal Injury Attorney"
  - Workers comp page missing "work injury" → add "Work Injury Claim"
  - Criminal page missing a key sub-topic → add "Felony Defense" or "Misdemeanor Lawyer"
If you cannot identify a genuine, specific gap — skip this section. Do NOT pad.

FORMAT RULES (all sections):
- Keyword phrases ONLY. No questions, no sentences, no punctuation (?, !, .)
- Separate sections with pipes ( | ); separate terms within sections with dashes ( - )
- Do not repeat the visible portion's exact phrase verbatim

COMPLETE EXAMPLE:
  Visible:   "DUI Lawyer San Jose | Experienced DUI Defense Attorneys"   ← CTA confirmed: yes, so no trust phrase needed
  Actually — CTA IS "Free Consultation" (confirmed). So:
  Visible:   "DUI Lawyer San Jose | Free Consultation"
  Section A: [skipped — CTA already in visible]
  Section B: "| San Jose DUI Attorney - Drunk Driving Lawyer California"
  Section C: "- DWI Defense - License Suspension Attorney"
  Full title: "DUI Lawyer San Jose | Free Consultation | San Jose DUI Attorney - Drunk Driving Lawyer California - DWI Defense - License Suspension Attorney"

  NO-CTA EXAMPLE:
  Visible:   "Omaha Child Injury Lawyer | Nebraska"
  Section A: "| Trusted Child Injury Attorneys"
  Section B: "| Nebraska Child Injury Attorney - Pediatric Injury Lawyer"
  Section C: "- Child Accident Claim - Minor Injury Lawsuit"
  Full title: "Omaha Child Injury Lawyer | Nebraska | Trusted Child Injury Attorneys | Nebraska Child Injury Attorney - Pediatric Injury Lawyer - Child Accident Claim"

Total title target: 140–220 characters.

---

## Meta Description (150–160 characters)

- Open with the searcher's situation or the query itself
- Include the top search query naturally in the first half
- Add ONE differentiator if inferable from the URL or current content (city, practice area)
- If a CTA exists in the current title/meta, mirror it here
- If no CTA exists in current content, end with a neutral action phrase ("Contact us today" / "Learn more")
- The brand/firm name belongs HERE (in the meta), NOT in the title tag. If you can infer
  the firm name from the current title or URL, include it naturally in the meta description.
  Example: "...call the team at Sabbeth Law today." — this is where branding lives.
- Do NOT start the meta with the firm name — it should appear mid-sentence or at the end
- Target 155 characters exactly

---

## Using Competitor Context

- Identify patterns in 2+ top results (signals what works in this SERP)
- Differentiate — don't copy their exact phrasing
- Use competitor keyword patterns for the extended tail, not the visible hook

---

## Output Format

Return ONLY a valid JSON array. One object per page, in the same order as the input.
{{
  "recommended_title": "Full title — visible hook + extended tail combined",
  "visible_portion": "The ≤60-character hook searchers see in the SERP",
  "extended_portion": "Everything after character 60 (keyword tail)",
  "title_char_count": 162,
  "recommended_meta": "150-160 character meta description",
  "rationale": "One sentence: what specific change this makes and why"
}}

Do not include any text before or after the JSON array."""


def _build_system_prompt() -> str:
    """Build the system prompt with the current trust words list injected."""
    words = config.load_trust_words()
    word_list = ", ".join(words)
    return _SYSTEM_PROMPT_TEMPLATE.format(trust_words=word_list)


_NON_ENGLISH_PATH_SEGMENTS = {"/es/", "/fr/", "/pt/", "/de/", "/it/", "/zh/", "/ko/", "/ja/"}


_LEGAL_SLUG_TERMS = {
    # Legal services
    "lawyer", "attorney", "attorneys", "lawyers", "law", "firm", "legal",
    "defense", "criminal", "dui", "dwi", "owi", "oui",
    "personal", "injury", "accident", "car", "auto", "truck", "motorcycle",
    "bicycle", "pedestrian", "slip", "fall", "wrongful", "death", "birth",
    "medical", "malpractice", "workers", "comp", "compensation",
    "divorce", "family", "custody", "child", "support", "adoption",
    "estate", "planning", "probate", "wills", "trusts", "elder",
    "immigration", "visa", "deportation", "asylum", "citizenship",
    "bankruptcy", "chapter", "debt", "employment", "civil", "litigation",
    "felony", "misdemeanor", "traffic", "speeding", "assault", "battery",
    "theft", "drug", "domestic", "violence", "sex", "crimes",
    "bond", "hearing", "appeals", "removal", "proceedings",
    "practice", "areas", "office", "offices", "services",
    # Navigation / generic
    "free", "consultation", "page", "about", "contact", "home",
    "blog", "news", "resources", "faqs", "faq", "guide", "help",
    # Prepositions / articles
    "the", "of", "and", "in", "at", "for", "a", "an", "to",
    # Descriptors / modifiers that are NOT cities
    "top", "best", "experienced", "trusted", "local", "affordable",
    "court", "courts", "case", "cases", "claim", "claims",
    "residency", "requirements", "consequences", "penalties",
    "charges", "charge", "school", "schools", "dui", "programs",
    "county", "counties", "district", "metro",
    "near", "me", "online", "virtual", "remote",
    "high", "net", "worth", "complex", "simple",
    "consumer", "commercial", "corporate", "federal", "state",
    "first", "second", "third", "offense", "offenses",
    "practices", "practice", "areas",  # URL nav segments
}

def _extract_city_from_url(url: str) -> str:
    """
    Extract the target city from a URL slug. Returns city name (title-cased) or ''.

    Strategy:
    1. Try the last path segment first (the page slug).
    2. If no city found there, try the penultimate segment (handles /state/page/ patterns).
    3. Filter out all known legal/generic terms — what remains must be ≤2 words.

    Examples:
      /santa-clara-criminal-lawyer/ → "Santa Clara"
      /dui-lawyer-san-jose/         → "San Jose"
      /new-hampshire/medical-malpractice-lawyer/ → "New Hampshire" (from parent segment)
      /pedestrian-accident-lawyers/  → "" (no city)
    """
    from urllib.parse import urlparse
    path = urlparse(url).path.lower().strip("/")
    segments = [s for s in path.split("/") if s]

    def _extract_from_slug(slug: str) -> str:
        words = [w for w in slug.split("-") if w and w not in _LEGAL_SLUG_TERMS]
        if not words or len(words) > 2:
            return ""
        city = " ".join(w.capitalize() for w in words)
        # Must look like a proper place name (at least 3 chars)
        if len(city) < 3:
            return ""
        return city

    # Try last segment, then penultimate
    for seg in reversed(segments[-2:]) if len(segments) >= 2 else segments[-1:]:
        result = _extract_from_slug(seg)
        if result:
            return result

    return ""


def _detect_language_note(page: PageOpportunity) -> str:
    """Return a language warning string if the page is clearly non-English."""
    url_lower = page.page_url.lower()
    for seg in _NON_ENGLISH_PATH_SEGMENTS:
        if seg in url_lower:
            lang_map = {
                "/es/": "Spanish", "/fr/": "French", "/pt/": "Portuguese",
                "/de/": "German",  "/it/": "Italian", "/zh/": "Chinese",
                "/ko/": "Korean",  "/ja/": "Japanese",
            }
            return f"⚠️ NON-ENGLISH PAGE ({lang_map.get(seg, 'non-English')}): write ALL output in {lang_map.get(seg, 'the same language as the current title')}."
    return ""


def _extract_cta_from_content(title: str, meta: str) -> str:
    """
    Scan current title and meta for a CTA the firm already uses.
    Returns the CTA phrase, or empty string if none found.
    """
    import re
    combined = f"{title} {meta}".lower()
    cta_patterns = [
        (r"free case review",    "Free Case Review"),
        (r"free consultation",   "Free Consultation"),
        (r"free consult",        "Free Consultation"),
        (r"no fee unless",       "No Fee Unless We Win"),
        (r"available 24[/\s]?7", "Available 24/7"),
        (r"call (?:us )?today",  "Call Today"),
        (r"call now",            "Call Now"),
        (r"schedule.*consult",   "Schedule a Consultation"),
        (r"contact us today",    "Contact Us Today"),
    ]
    for pattern, label in cta_patterns:
        if re.search(pattern, combined):
            return label
    return ""


def _format_page_block(page: PageOpportunity, idx: int) -> str:
    """Format one page's data for inclusion in the AI prompt."""
    lang_note = _detect_language_note(page)
    confirmed_cta = _extract_cta_from_content(page.current_title, page.current_meta)

    url_city = _extract_city_from_url(page.page_url)

    lines = [f"Page {idx + 1}:"]
    if lang_note:
        lines.append(f"  {lang_note}")
    lines += [
        f"  URL: {page.page_url}",
    ]
    if url_city:
        lines.append(
            f"  ⚠️  TARGET CITY FROM URL SLUG: {url_city}"
            f" — USE THIS CITY in the title, NOT any city mentioned in the top query."
            f" The URL is the authoritative geo signal for this page."
        )
    lines += [
        f"  Top search query (use the SERVICE/PRACTICE AREA terms verbatim; use URL city for geo): {page.top_query}",
        f"  Current position: {page.position:.1f}",
        f"  Actual CTR: {page.ctr*100:.1f}%  (expected: {page.expected_ctr*100:.1f}%)",
        f"  Client: {page.client_name}",
        f"  Current title: {page.current_title or '[not fetched]'}",
        f"  Current meta: {page.current_meta or '[not fetched]'}",
        f"  Confirmed CTA from existing content: {confirmed_cta if confirmed_cta else '[NONE — do not add a CTA to the visible title]'}",
    ]

    # Secondary queries from GSC — the real data source for the extended title tail
    if page.secondary_queries:
        lines.append(f"  Secondary queries from GSC (use in extended tail — real proven searches for this page):")
        for q in page.secondary_queries:
            lines.append(f"    - {q}")
    else:
        lines.append("  Secondary queries from GSC: [none — use competitor context and practice area terms for extended tail]")

    if page.competitor_serps:
        lines.append("  Competitor titles/metas ranking above this page:")
        for c in page.competitor_serps:
            lines.append(f"    #{c.position}: Title: {c.title}")
            if c.meta:
                lines.append(f"         Meta:  {c.meta}")
    return "\n".join(lines)


def _call_api(pages_block: list) -> list:
    """
    Call OpenRouter with a batch of pages.
    Returns list of dicts (one per page) or empty list on failure.
    """
    user_content = (
        f"Rewrite the title tags and meta descriptions for these {len(pages_block)} page(s). "
        f"Return a JSON array with exactly {len(pages_block)} objects in the same order.\n\n"
        + "\n\n".join(_format_page_block(p, i) for i, p in enumerate(pages_block))
    )

    for attempt in range(config.MAX_RETRIES + 1):
        try:
            response = _get_client().chat.completions.create(
                model=config.AI_MODEL,
                messages=[
                    {"role": "system", "content": _build_system_prompt()},
                    {"role": "user",   "content": user_content},
                ],
                temperature=0.7,
                max_tokens=4000,
            )
            raw = response.choices[0].message.content.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.rsplit("```", 1)[0].strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list) and len(parsed) == len(pages_block):
                return parsed
            print(f"    ⚠️  AI returned {len(parsed)} items for {len(pages_block)} pages — retrying")

        except json.JSONDecodeError as e:
            print(f"    ⚠️  JSON parse error (attempt {attempt+1}): {e}")
        except Exception as e:
            print(f"    ⚠️  API error (attempt {attempt+1}): {e}")

        if attempt < config.MAX_RETRIES:
            wait = config.BACKOFF_BASE ** attempt
            time.sleep(wait)

    return []


def _apply_rewrites(pages: list, rewrites: list):
    """Write AI output fields onto PageOpportunity objects."""
    for page, rw in zip(pages, rewrites):
        if not isinstance(rw, dict):
            continue
        page.recommended_title = rw.get("recommended_title", "")
        page.visible_portion   = rw.get("visible_portion", "")
        page.extended_portion  = rw.get("extended_portion", "")
        page.recommended_meta  = rw.get("recommended_meta", "")
        page.rationale         = rw.get("rationale", "")

        # Compute char count from actual recommended_title length
        page.title_char_count = len(page.recommended_title)


# ── Main entry point ───────────────────────────────────────────────────────────

def run(pages: list) -> list:
    """
    Entry point for Step 5.
    Generates rewrites for all flagged pages. Returns the same list (mutated).
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 5 — Generating AI title and meta rewrites")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not pages:
        return pages

    print(f"  {len(pages)} pages to rewrite | model: {config.AI_MODEL} | batch size: {config.AI_BATCH_SIZE}\n")

    # Group pages by client to keep context cohesive
    by_client = {}
    for page in pages:
        by_client.setdefault(page.client_name, []).append(page)

    total_done = 0
    total_clients = len(by_client)

    for ci, (client_name, client_pages) in enumerate(by_client.items(), 1):
        print(f"  [{ci}/{total_clients}] {client_name} — {len(client_pages)} page(s)")

        # Split into batches of AI_BATCH_SIZE
        for batch_start in range(0, len(client_pages), config.AI_BATCH_SIZE):
            batch = client_pages[batch_start:batch_start + config.AI_BATCH_SIZE]
            rewrites = _call_api(batch)

            if rewrites:
                _apply_rewrites(batch, rewrites)
                total_done += len(batch)
                print(f"    ✅ Batch {batch_start//config.AI_BATCH_SIZE + 1}: {len(batch)} page(s) rewritten")
            else:
                print(f"    ❌ Batch {batch_start//config.AI_BATCH_SIZE + 1}: failed after {config.MAX_RETRIES} retries — leaving blank")

    failed = sum(1 for p in pages if not p.recommended_title)
    print(
        f"\n  ✅ Step 5 complete — "
        f"{total_done}/{len(pages)} pages rewritten | "
        f"{failed} failed."
    )

    return pages
