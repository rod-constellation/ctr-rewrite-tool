"""
Step 6 — Write Outputs

Produces two outputs:
  1. Local CSV report at reports/ctr_rewrite_report_YYYY-MM-DD.csv
  2. Google Sheet in the configured Drive folder with:
       - MASTER tab (all flagged pages, sorted by CTR gap)
       - Per-strategist tabs (their assigned clients' pages)
       - Baseline Log tab (for VA tracking post-deployment)

Reuses _build_services, _create_sheet, _write_tab, _format_tab, _move_to_folder
patterns from Striking Distance Keywords Tactic step5_sheets.py.
"""

import csv
import os
import time
from datetime import date, timedelta
from urllib.parse import urlparse

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

import config
from models import PageOpportunity


# ── CSV columns ────────────────────────────────────────────────────────────────

CSV_HEADERS = [
    "Client", "Strategist", "Client Status", "Page URL", "Target Query",
    "Current Position", "Current CTR %", "Expected CTR %", "CTR Gap %",
    "Impressions", "Current Title Tag", "Recommended Title Tag",
    "Visible Portion (≤60 chars)", "Extended Portion (60+ chars)", "Title Char Count",
    "Current Meta Description", "Recommended Meta Description", "Rationale",
    "Analysis Date",
]

SHEET_HEADERS = [
    "DATE", "COMPLETED",
    "Page URL", "Target Query", "Current Position", "Current CTR %",
    "Expected CTR %", "CTR Gap %", "Current Title Tag", "Recommended Title Tag",
    "Title Char Count", "Current Meta Description", "Recommended Meta Description",
    "Rationale", "Client Status",
]

BASELINE_HEADERS = [
    "Client", "Strategist", "Page URL", "Target Query",
    "Baseline CTR %", "Baseline Position", "Analysis Date",
    "Date Changes Deployed", "Measurement Date",
    "Post-Change CTR %", "Post-Change Position",
]

# ── Styling ────────────────────────────────────────────────────────────────────

_HEADER_COLOR    = {"red": 0.788, "green": 0.855, "blue": 0.973}  # #C9DAF8 light blue
_RED_COLOR       = {"red": 0.918, "green": 0.600, "blue": 0.600}  # light red header
_RED_ROW_COLOR   = {"red": 0.980, "green": 0.898, "blue": 0.898}  # very light red for flagged rows
_YELLOW_HEADER   = {"red": 1.0,   "green": 1.0,   "blue": 0.0}    # Yellow — DATE/COMPLETED cols
_COMPLETED_GREEN = {"red": 0.220, "green": 0.463, "blue": 0.114}  # Dark green 2 (#38761D)

_COL_WIDTHS = {
    "DATE": 100, "COMPLETED": 110,
    "Page URL": 300, "Target Query": 220, "Current Position": 120,
    "Current CTR %": 110, "Expected CTR %": 110, "CTR Gap %": 100,
    "Current Title Tag": 280, "Recommended Title Tag": 360,
    "Visible Portion (≤60 chars)": 280, "Extended Portion (60+ chars)": 360,
    "Title Char Count": 120,
    "Current Meta Description": 280, "Recommended Meta Description": 360,
    "Rationale": 400, "Client Status": 120,
    "Client": 200, "Strategist": 160,
    "Analysis Date": 120, "Baseline CTR %": 110,
    "Baseline Position": 120, "Date Changes Deployed": 150,
    "Measurement Date": 130, "Post-Change CTR %": 130,
    "Post-Change Position": 140,
}

_CENTERED_COLS = {
    "Current Position", "Current CTR %", "Expected CTR %", "CTR Gap %",
    "Title Char Count", "Client Status", "Analysis Date", "Baseline CTR %",
    "Baseline Position", "Measurement Date", "Post-Change CTR %", "Post-Change Position",
}


# ── Auth (same pattern as Striking Distance step5_sheets.py) ──────────────────

def _build_services():
    refresh_token = config.GOOGLE_SHEETS_REFRESH_TOKEN or config.GOOGLE_REFRESH_TOKEN
    scopes = config.GOOGLE_SHEETS_SCOPES if config.GOOGLE_SHEETS_REFRESH_TOKEN else config.GOOGLE_SCOPES
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=config.GOOGLE_CLIENT_ID,
        client_secret=config.GOOGLE_CLIENT_SECRET,
        scopes=scopes,
    )
    creds.refresh(Request())
    sheets = build("sheets", "v4", credentials=creds)
    drive  = build("drive",  "v3", credentials=creds)
    return sheets, drive


# ── Sheet helpers (adapted from Striking Distance step5_sheets.py) ─────────────

def _col(n: int) -> str:
    result = ""
    while n:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _create_sheet(sheets_svc, title: str, tab_names: list) -> tuple:
    body = {
        "properties": {"title": title},
        "sheets": [{"properties": {"title": name}} for name in tab_names],
    }
    result = sheets_svc.spreadsheets().create(body=body, fields="spreadsheetId,sheets").execute()
    spreadsheet_id = result["spreadsheetId"]
    tab_ids = {
        sheet["properties"]["title"]: sheet["properties"]["sheetId"]
        for sheet in result["sheets"]
    }
    return spreadsheet_id, tab_ids


def _write_tab(sheets_svc, spreadsheet_id: str, tab_name: str, rows: list):
    if not rows:
        return
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{tab_name}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def _format_tab(sheets_svc, spreadsheet_id: str, sheet_id: int,
                headers: list, num_data_rows: int,
                header_color: dict = None, has_red_flagged: bool = False):
    """Apply standard formatting: freeze header, bold, column widths, filter."""
    header_color = header_color or _HEADER_COLOR
    num_cols = len(headers)
    total_rows = num_data_rows + 1

    requests = [
        # Freeze header row
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
        # All cells — wrap + middle vertical alignment (entire sheet)
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": num_cols},
            "cell": {"userEnteredFormat": {
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat(verticalAlignment,wrapStrategy)",
        }},
        # Header styling (applied after, overrides the above for row 0)
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": num_cols},
            "cell": {"userEnteredFormat": {
                "backgroundColor": header_color,
                "textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
        }},
        # Header row height
        {"updateDimensionProperties": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": 45},
            "fields": "pixelSize",
        }},
    ]

    # Trim excess rows / cols
    if total_rows < 1000:
        requests.append({"deleteDimension": {
            "range": {"sheetId": sheet_id, "dimension": "ROWS",
                      "startIndex": total_rows, "endIndex": 1000}
        }})
    if num_cols < 26:
        requests.append({"deleteDimension": {
            "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                      "startIndex": num_cols, "endIndex": 26}
        }})

    # Column widths
    for ci, header in enumerate(headers):
        if header in _COL_WIDTHS:
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": ci, "endIndex": ci + 1},
                "properties": {"pixelSize": _COL_WIDTHS[header]},
                "fields": "pixelSize",
            }})

    # Center-align numeric/status columns (horizontal only — wrap+middle already applied above)
    for ci, header in enumerate(headers):
        if header in _CENTERED_COLS:
            requests.append({"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                          "endRowIndex": max(total_rows, 2),
                          "startColumnIndex": ci, "endColumnIndex": ci + 1},
                "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
                "fields": "userEnteredFormat(horizontalAlignment)",
            }})

    # Red row highlight for FLAGGED clients (if Client Status column exists)
    if has_red_flagged and "Client Status" in headers:
        cs_idx = headers.index("Client Status")
        cs_col = _col(cs_idx + 1)
        requests.append({"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 1,
                            "endRowIndex": max(total_rows, 2),
                            "startColumnIndex": 0, "endColumnIndex": num_cols}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": f'=${cs_col}2="FLAGGED"'}]},
                    "format": {"backgroundColor": _RED_ROW_COLOR},
                },
            },
            "index": 0,
        }})

    # Basic filter
    requests.append({"setBasicFilter": {"filter": {
        "range": {"sheetId": sheet_id, "startRowIndex": 0, "startColumnIndex": 0,
                  "endRowIndex": total_rows, "endColumnIndex": num_cols}
    }}})

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def _format_date_completed_extras(sheets_svc, spreadsheet_id: str, sheet_id: int, num_data_rows: int):
    """
    Apply DATE / COMPLETED column formatting — identical to Striking Distance step5_sheets.py.
    - Yellow header background on cols A (DATE) and B (COMPLETED)
    - Date picker validation on col A data cells
    - Checkbox validation on col B data cells
    - Entire row turns dark green (#38761D) when COMPLETED checkbox is ticked
    Call AFTER _format_tab so the green rule lands at index 0 (highest priority).
    """
    total_rows = num_data_rows + 1
    num_cols   = len(SHEET_HEADERS)

    requests = [
        # Yellow header on DATE (col A) and COMPLETED (col B)
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 2},
            "cell": {"userEnteredFormat": {
                "backgroundColor": _YELLOW_HEADER,
                "textFormat": {"bold": True, "foregroundColor": {"red": 0, "green": 0, "blue": 0}},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
        }},
        # Date validation — col A data cells
        {"setDataValidation": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "endRowIndex": max(total_rows, 2),
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "rule": {"condition": {"type": "DATE_IS_VALID"}, "showCustomUi": True, "strict": False},
        }},
        # Checkbox — col B data cells
        {"setDataValidation": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "endRowIndex": max(total_rows, 2),
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "rule": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True},
        }},
        # Row turns dark green + white text when COMPLETED (col B) = TRUE
        {"addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": sheet_id, "startRowIndex": 1,
                            "endRowIndex": max(total_rows, 2),
                            "startColumnIndex": 0, "endColumnIndex": num_cols}],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": "=$B2=TRUE"}]},
                    "format": {
                        "backgroundColor": _COMPLETED_GREEN,
                        "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    },
                },
            },
            "index": 0,  # highest priority — overrides all other conditional formats
        }},
    ]

    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()


def _set_tab_color(sheets_svc, spreadsheet_id: str, sheet_id: int, color: dict):
    sheets_svc.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "tabColorStyle": {"rgbColor": color}},
            "fields": "tabColorStyle",
        }}]},
    ).execute()


def _move_to_folder(drive_svc, spreadsheet_id: str, folder_id: str):
    file_meta = drive_svc.files().get(
        fileId=spreadsheet_id, fields="parents", supportsAllDrives=True
    ).execute()
    current_parents = ",".join(file_meta.get("parents", []))
    drive_svc.files().update(
        fileId=spreadsheet_id,
        addParents=folder_id,
        removeParents=current_parents,
        fields="id,parents",
        supportsAllDrives=True,
    ).execute()


def _next_version_letter(drive_svc, today: str) -> str:
    """
    Check Drive for existing sheets with today's date and return the next
    version letter: blank if none exist, B if one exists, C if two, etc.
    First run of the day → no suffix. Second → B. Third → C. And so on.
    """
    base = f"CTR Rewrite Recommendations — {today}"
    try:
        results = drive_svc.files().list(
            q=f"name contains '{base}' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            fields="files(name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        count = len(results.get("files", []))
    except Exception:
        count = 0
    if count == 0:
        return ""
    # A=0 already exists, so next is B(1), C(2), ...
    return " " + chr(ord("B") + count - 1)


# ── Row builders ───────────────────────────────────────────────────────────────

def _page_to_sheet_row(p: PageOpportunity) -> list:
    return [
        "",     # DATE — VA fills in when changes are deployed
        False,  # COMPLETED — checkbox, VA ticks when done
        p.page_url,
        p.top_query,
        round(p.position, 1),
        f"{p.ctr*100:.2f}%",
        f"{p.expected_ctr*100:.2f}%",
        f"{p.ctr_gap*100:.2f}%",
        p.current_title,
        p.recommended_title,
        p.title_char_count,
        p.current_meta,
        p.recommended_meta,
        p.rationale,
        "FLAGGED" if p.is_red_flag else "Normal",
    ]


def _page_to_baseline_row(p: PageOpportunity, analysis_date: str) -> list:
    measurement_date = (date.fromisoformat(analysis_date) + timedelta(days=14)).isoformat()
    return [
        p.client_name,
        p.strategist,
        p.page_url,
        p.top_query,
        f"{p.ctr*100:.2f}%",
        round(p.position, 1),
        analysis_date,
        "",                   # Date Changes Deployed — VA fills in
        measurement_date,
        "",                   # Post-Change CTR — filled at measurement
        "",                   # Post-Change Position — filled at measurement
    ]


def _page_to_csv_row(p: PageOpportunity) -> list:
    return [
        p.client_name,
        p.strategist,
        "FLAGGED" if p.is_red_flag else "Normal",
        p.page_url,
        p.top_query,
        round(p.position, 1),
        f"{p.ctr*100:.2f}%",
        f"{p.expected_ctr*100:.2f}%",
        f"{p.ctr_gap*100:.2f}%",
        p.impressions,
        p.current_title,
        p.recommended_title,
        p.visible_portion,
        p.extended_portion,
        p.title_char_count,
        p.current_meta,
        p.recommended_meta,
        p.rationale,
        p.analysis_date,
    ]


# ── Homepage detection (same logic as Striking Distance Keywords Tactic) ───────

def _is_homepage(url: str) -> bool:
    """Homepage = URL with no meaningful path (empty or just '/')."""
    path = urlparse(url).path.rstrip("/")
    return path == ""


# ── Main entry point ───────────────────────────────────────────────────────────

def run(pages: list) -> str:
    """
    Entry point for Step 6.
    Returns the Google Sheet URL.
    """
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 6 — Writing outputs")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    today = date.today().strftime("%Y-%m-%d")

    # Split homepages from regular pages — same pattern as Striking Distance.
    # Homepages require explicit client approval before changes are made,
    # so they go to a separate "* Needs Client Approval *" tab and are excluded
    # from strategist tabs and the MASTER tab.
    regular_pages  = [p for p in pages if not _is_homepage(p.page_url)]
    homepage_pages = [p for p in pages if _is_homepage(p.page_url)]

    if homepage_pages:
        print(f"  ℹ️  {len(homepage_pages)} homepage(s) moved to '* Needs Client Approval *' tab.")

    has_any_red = any(p.is_red_flag for p in regular_pages)

    # ── Local CSV (all pages including homepages, flagged for reference) ───────
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    csv_base = os.path.join(config.REPORTS_DIR, f"ctr_rewrite_report_{today}")
    csv_path = f"{csv_base}.csv"
    letter_idx = 1
    while os.path.exists(csv_path):
        csv_path = f"{csv_base}_{chr(ord('B') + letter_idx - 1)}.csv"
        letter_idx += 1
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        for p in pages:  # CSV keeps everything for archival
            writer.writerow(_page_to_csv_row(p))
    print(f"  ✅ Local CSV saved: {csv_path}")

    # ── Google Sheet ──────────────────────────────────────────────────────────
    sheets_svc, drive_svc = _build_services()

    # Determine tabs — regular pages only in MASTER + strategist tabs
    strategists = sorted({p.strategist for p in regular_pages if p.strategist})
    tab_names = ["MASTER"] + strategists
    if homepage_pages:
        tab_names.append("* Needs Client Approval *")
    tab_names.append("Baseline Log")

    version_letter = _next_version_letter(drive_svc, today)
    sheet_title = f"CTR Rewrite Recommendations — {today}{version_letter}"
    print(f"  Creating sheet: '{sheet_title}'")
    print(f"  Tabs: {', '.join(tab_names)}\n")

    spreadsheet_id, tab_ids = _create_sheet(sheets_svc, sheet_title, tab_names)
    sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    # ── MASTER tab (regular pages only — no homepages) ────────────────────────
    sorted_regular = sorted(regular_pages, key=lambda p: -p.ctr_gap)
    master_rows = [SHEET_HEADERS] + [_page_to_sheet_row(p) for p in sorted_regular]

    _write_tab(sheets_svc, spreadsheet_id, "MASTER", master_rows)
    _format_tab(sheets_svc, spreadsheet_id, tab_ids["MASTER"],
                SHEET_HEADERS, len(sorted_regular), has_red_flagged=has_any_red)
    _format_date_completed_extras(sheets_svc, spreadsheet_id, tab_ids["MASTER"], len(sorted_regular))
    print(f"  ✅ MASTER tab — {len(sorted_regular)} pages")

    # ── Per-strategist tabs (regular pages only) ──────────────────────────────
    for strategist in strategists:
        strat_pages = sorted(
            [p for p in regular_pages if p.strategist == strategist],
            key=lambda p: -p.ctr_gap
        )
        strat_rows = [SHEET_HEADERS] + [_page_to_sheet_row(p) for p in strat_pages]

        _write_tab(sheets_svc, spreadsheet_id, strategist, strat_rows)
        strat_has_red = any(p.is_red_flag for p in strat_pages)
        _format_tab(sheets_svc, spreadsheet_id, tab_ids[strategist],
                    SHEET_HEADERS, len(strat_pages),
                    header_color=_RED_COLOR if strat_has_red else None,
                    has_red_flagged=strat_has_red)
        _format_date_completed_extras(sheets_svc, spreadsheet_id, tab_ids[strategist], len(strat_pages))

        if strat_has_red:
            _set_tab_color(sheets_svc, spreadsheet_id, tab_ids[strategist],
                           {"red": 0.9, "green": 0.3, "blue": 0.3})
            time.sleep(0.3)

        print(f"  ✅ {strategist} tab — {len(strat_pages)} pages"
              + (" (red-flagged clients)" if strat_has_red else ""))
        time.sleep(0.5)

    # ── * Needs Client Approval * tab (homepages) ─────────────────────────────
    if homepage_pages:
        sorted_homepages = sorted(homepage_pages, key=lambda p: (p.strategist, -p.ctr_gap))
        approval_rows = [SHEET_HEADERS] + [_page_to_sheet_row(p) for p in sorted_homepages]

        _write_tab(sheets_svc, spreadsheet_id, "* Needs Client Approval *", approval_rows)
        _format_tab(sheets_svc, spreadsheet_id, tab_ids["* Needs Client Approval *"],
                    SHEET_HEADERS, len(sorted_homepages),
                    has_red_flagged=any(p.is_red_flag for p in homepage_pages))

        _format_date_completed_extras(sheets_svc, spreadsheet_id, tab_ids["* Needs Client Approval *"], len(sorted_homepages))
        # Yellow tab color to make it stand out
        _set_tab_color(sheets_svc, spreadsheet_id, tab_ids["* Needs Client Approval *"],
                       {"red": 1.0, "green": 0.85, "blue": 0.0})
        print(f"  ✅ * Needs Client Approval * tab — {len(homepage_pages)} homepage(s)")
        time.sleep(0.5)

    # ── Baseline Log tab (regular pages only — homepages not deployed yet) ────
    baseline_rows = [BASELINE_HEADERS]
    for p in sorted_regular:
        baseline_rows.append(_page_to_baseline_row(p, p.analysis_date or today))

    _write_tab(sheets_svc, spreadsheet_id, "Baseline Log", baseline_rows)
    _format_tab(sheets_svc, spreadsheet_id, tab_ids["Baseline Log"],
                BASELINE_HEADERS, len(sorted_regular))
    print(f"  ✅ Baseline Log tab — {len(sorted_regular)} pages")

    # ── Move to Drive folder ──────────────────────────────────────────────────
    try:
        _move_to_folder(drive_svc, spreadsheet_id, config.DRIVE_FOLDER_ID)
        print(f"  📁 Moved to Drive folder")
    except Exception as e:
        print(f"  ⚠️  Could not move to Drive folder: {e}")
        print(f"     Sheet is still accessible at the URL below.")

    print(f"\n  ✅ Step 6 complete.")
    print(f"\n  📊 Sheet URL: {sheet_url}\n")
    print(f"  📄 Local CSV: {csv_path}\n")

    return sheet_url
