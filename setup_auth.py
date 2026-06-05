"""
One-time Google OAuth setup script.

Two modes:

  python3 setup_auth.py
    Authorizes the AGENCY Google account (the one with Search Console access
    for all clients). Writes GOOGLE_REFRESH_TOKEN to .env.

  python3 setup_auth.py --sheets
    Authorizes YOUR PERSONAL Google account (rodrigo@goconstellation.com)
    for Sheets + Drive only — so the output sheet lands in your own Drive.
    Writes GOOGLE_SHEETS_REFRESH_TOKEN to .env.

Run each mode once. After both are done, python3 main.py uses the agency
account for GSC data and your personal account for creating the Sheet.

NOTE: If you already have valid tokens in Striking Distance Keywords Tactic/.env,
copy them to this project's .env instead of running this script.
"""

import argparse
import os
import sys

CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "client_secret.json")
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

AGENCY_SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sheets", action="store_true",
        help="Authorize personal account for Sheets/Drive (writes GOOGLE_SHEETS_REFRESH_TOKEN)"
    )
    args = parser.parse_args()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("❌ Missing dependency. Run:  pip3 install google-auth-oauthlib")
        sys.exit(1)

    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"❌ client_secret.json not found at: {CLIENT_SECRET_FILE}")
        print("   Download it from Google Cloud Console > APIs & Services > Credentials.")
        sys.exit(1)

    if args.sheets:
        scopes    = SHEETS_SCOPES
        token_key = "GOOGLE_SHEETS_REFRESH_TOKEN"
        print("Opening browser to authorize your PERSONAL Google account...")
        print("Log in as rodrigo@goconstellation.com (or whichever account owns the Drive folder).")
        print("This account only needs Sheets + Drive access — NOT Search Console.")
    else:
        scopes    = AGENCY_SCOPES
        token_key = "GOOGLE_REFRESH_TOKEN"
        print("Opening browser to authorize the AGENCY Google account...")
        print("Log in as the account that has Search Console access for all clients.")
    print()

    flow  = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, scopes=scopes)
    creds = flow.run_local_server(port=0)

    client_id     = creds.client_id
    client_secret = creds.client_secret
    refresh_token = creds.refresh_token

    print("\n✅ Authorization successful!")
    print()
    if args.sheets:
        print("Add this line to your .env file:")
        print("─" * 60)
        print(f"{token_key}={refresh_token}")
        print("─" * 60)
    else:
        print("Add these lines to your .env file:")
        print("─" * 60)
        print(f"GOOGLE_CLIENT_ID={client_id}")
        print(f"GOOGLE_CLIENT_SECRET={client_secret}")
        print(f"{token_key}={refresh_token}")
        print("─" * 60)

    answer = input("\nWrite to your .env file automatically? (y/n): ").strip().lower()
    if answer == "y":
        existing = ""
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, "r") as f:
                existing = f.read()

        keys_to_remove = {token_key}
        if not args.sheets:
            keys_to_remove |= {"GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"}

        lines = [
            line for line in existing.splitlines()
            if not any(line.startswith(f"{k}=") for k in keys_to_remove)
        ]
        lines.append("")
        if args.sheets:
            lines.append("# Google OAuth (personal account — Sheets/Drive)")
            lines.append(f"{token_key}={refresh_token}")
        else:
            lines.append("# Google OAuth (agency account — Search Console + Sheets)")
            lines.append(f"GOOGLE_CLIENT_ID={client_id}")
            lines.append(f"GOOGLE_CLIENT_SECRET={client_secret}")
            lines.append(f"{token_key}={refresh_token}")

        with open(ENV_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")

        print(f"✅ Written to {ENV_FILE}")
        if args.sheets:
            print("\nPersonal account authorized. Run:  python3 main.py")
        else:
            print("\nAgency account authorized.")
            print("Now run:  python3 setup_auth.py --sheets")
    else:
        print("\nCopy the line(s) above into your .env file manually.")


if __name__ == "__main__":
    main()
