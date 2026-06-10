"""
Configuration for the CTR Optimization Tool.
All tunable settings are here — no need to touch step files.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Google OAuth ───────────────────────────────────────────────────────────────

GOOGLE_CLIENT_ID            = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET        = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN        = os.environ.get("GOOGLE_REFRESH_TOKEN", "")        # agency — GSC
GOOGLE_SHEETS_REFRESH_TOKEN = os.environ.get("GOOGLE_SHEETS_REFRESH_TOKEN", "") # personal — Sheets/Drive

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
GOOGLE_SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Ahrefs ────────────────────────────────────────────────────────────────────

AHREFS_API_KEY   = os.environ.get("AHREFS_API_KEY", "")
AHREFS_BASE_URL  = "https://api.ahrefs.com/v3"
AHREFS_SLEEP     = 0.5
PAGE_SIZE        = 1000
REQUEST_TIMEOUT  = 30
MAX_RETRIES      = 3
BACKOFF_BASE     = 2  # exponential: 2s, 4s, 8s

# ── OpenRouter (Kimi K2) ──────────────────────────────────────────────────────

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
AI_MODEL           = "moonshotai/kimi-k2"    # change here if model ID differs
AI_BATCH_SIZE      = 10                       # pages per AI API call

# ── DataForSEO SERP ───────────────────────────────────────────────────────────

DATAFORSEO_LOGIN    = os.environ.get("DATAFORSEO_LOGIN", "")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD", "")
SERP_SLEEP          = 0.3
SERP_RESULT_COUNT   = 5    # top N competitor positions to send to AI prompt
SERP_FETCH_DEPTH    = 15   # how deep to fetch — must cover our page's position (5–12)
                            # so we can find the client's own title/meta from Google's SERP
DATAFORSEO_LOCATION = 2840  # US

# ── GSC filters — adjust these to widen / narrow the candidate page list ───────

GSC_MIN_IMPRESSIONS = 500   # lower to include low-traffic pages
GSC_MIN_POSITION    = 5     # lower to include top-ranking pages (e.g. 4 or 3)
GSC_MAX_POSITION    = 12    # raise to include deeper positions (e.g. 15 or 20)
GSC_LOOKBACK_DAYS   = 90
GSC_SLEEP           = 0.3
GSC_ROW_LIMIT       = 25000

# Secondary queries extracted from GSC — used to build the extended title tail.
# These are real queries the page already ranks for, extracted directly from GSC data.
GSC_SECONDARY_QUERIES_COUNT    = 8   # how many secondary queries to keep per page
GSC_SECONDARY_MIN_IMPRESSIONS  = 30  # ignore queries with fewer impressions (noise)

# ── Service page detection ────────────────────────────────────────────────────
# Only service/transactional pages get the extended title rewrite treatment.
# Blog posts and informational articles are skipped — CTR improvements there
# don't meaningfully drive leads.

# If the top query contains ANY of these terms → service/transactional page.
SERVICE_QUERY_KEYWORDS = [
    "attorney", "lawyer", "law firm", "legal services", "legal help",
    "law office", "counsel", "solicitor", "litigation", "legal advice",
    "law group", "legal group", "attorneys", "lawyers", "esquire",
]

# If the page URL contains ANY of these patterns → informational/blog content.
# Used as a secondary filter when the query doesn't have clear service intent.
BLOG_URL_PATTERNS = [
    "/blog/", "/news/", "/article", "/resources/", "/faq/",
    "/legal-guide", "/guide/", "/videos/", "/podcast/", "/insight",
    "/post/", "/press/", "/media/", "/newsletter",
]

# File extensions that can't have title/meta updated via CMS — skip entirely.
# PDFs, Word docs, PowerPoints etc. require editing the file itself, not a page template.
EXCLUDED_URL_EXTENSIONS = [
    ".pdf", ".doc", ".docx", ".pptx", ".ppt",
    ".xls", ".xlsx", ".odt", ".odp", ".ods", ".rtf", ".txt",
]

# ── CTR classification ─────────────────────────────────────────────────────────

# Flag a page if actual_CTR <= CTR_THRESHOLD_RATIO × expected_CTR.
# Lower = fewer pages flagged (only severe underperformers).
# Higher = more pages flagged (catches borderline cases too).
CTR_THRESHOLD_RATIO        = 0.70
INTERNAL_CURVE_MIN_SAMPLES = 30  # buckets with fewer pages fall back to benchmark

# Benchmark CTR by position (mid-point estimates for legal/attorney SERPs).
# Used when a position bucket has fewer than INTERNAL_CURVE_MIN_SAMPLES pages.
CTR_BENCHMARK = {
    5:  0.055,
    6:  0.045,
    7:  0.035,
    8:  0.030,
    9:  0.025,
    10: 0.0225,
    11: 0.0175,
    12: 0.0175,
}

# ── Page fetch ─────────────────────────────────────────────────────────────────

HTTP_FETCH_SLEEP  = 0.5
FETCH_CONCURRENCY = 10
FETCH_TIMEOUT     = 10

# ── Google IDs ─────────────────────────────────────────────────────────────────

DRIVE_FOLDER_ID          = "18KlaH2hlGEXJs-9fk1e8R-_S0N-aoRoS"
STRATEGIST_SHEET_ID      = "1sX4Y9XhP4esV5PA_QSsro46rKDBKXDWMrKIA-85CGRo"
CLASSIFICATION_SHEET_GID = "584907407"   # tab with Column R red-flag status

SHARE_WITH_EMAIL = "rodrigo@goconstellation.com"

# ── Paths ──────────────────────────────────────────────────────────────────────

BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR      = os.path.join(BASE_DIR, "reports")
TRUST_WORDS_FILE = os.path.join(BASE_DIR, "config", "trust_words.txt")


def load_trust_words() -> list:
    """
    Load active trust words from config/trust_words.txt.
    Returns only uncommented, non-empty lines.
    Edit that file to add/remove words — no code changes needed.
    """
    if not os.path.exists(TRUST_WORDS_FILE):
        return ["trusted", "experienced", "dedicated"]  # safe fallback
    words = []
    with open(TRUST_WORDS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                words.append(line)
    return words


# ── Validation ─────────────────────────────────────────────────────────────────

def validate():
    """Raise EnvironmentError if any required env var is missing."""
    required = {
        "GOOGLE_CLIENT_ID":     GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "GOOGLE_REFRESH_TOKEN": GOOGLE_REFRESH_TOKEN,
        "AHREFS_API_KEY":       AHREFS_API_KEY,
        "OPENROUTER_API_KEY":   OPENROUTER_API_KEY,
        "DATAFORSEO_LOGIN":     DATAFORSEO_LOGIN,
        "DATAFORSEO_PASSWORD":  DATAFORSEO_PASSWORD,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Copy them from existing project .env files — see .env.example."
        )
