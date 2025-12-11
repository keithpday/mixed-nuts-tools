#!/usr/bin/env python3

import datetime
import pytz
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

SPREADSHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SHEET_RANGE     = "CurrentYrSched!A:Z"

CALENDAR_ID = "appsoni.com_dump9u7hsmk3tj5dt82u2tesj0@group.calendar.google.com"

# Column indexes (zero-based)
COL_DATE        = 1   # Column B
COL_TIME        = 3   # Column D
COL_LOCATION    = 4   # Column E
COL_SET         = 5   # Column F

# ----------------------------------------------------------------------
def load_google_services():
    """Authorize Sheets + Calendar service clients."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/calendar"
    ]

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    SCRIPT_NAME = "calendar_sync_utility_v1"  # You can change this later if needed

    BASE_CONFIG_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config"

    CREDENTIALS_PATH = f"{BASE_CONFIG_PATH}/credentials.json"
    TOKEN_PATH       = f"{BASE_CONFIG_PATH}/{SCRIPT_NAME}_token.json"

    creds = None

    # ------------------------------------------------------------------
    # Load existing token (if present)
    # ------------------------------------------------------------------
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # ------------------------------------------------------------------
    # If no valid token, run OAuth flow
    # ------------------------------------------------------------------
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        # Save token under script-specific name
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    # ------------------------------------------------------------------
    # Build service clients
    # ------------------------------------------------------------------
    sheets = build("sheets", "v4", credentials=creds)
    calendar = build("calendar", "v3", credentials=creds)
    return sheets, calendar


# ----------------------------------------------------------------------
def parse_time_range(date_str, time_range_str):
    """Convert '6:00 p - 8:00 p' into RFC3339 datetime strings."""
    date = datetime.datetime.strptime(date_str, "%m/%d/%Y").date()

    def convert(t):
        t = t.strip().lower().replace(" ", "")
        if t.endswith("p"):
            base = datetime.datetime.strptime(t[:-1], "%I:%M")
            return (base + datetime.timedelta(hours=12)).time()
        else:
            return datetime.datetime.strptime(t[:-1], "%I:%M").time()

    try:
        start_raw, end_raw = time_range_str.split("-")
        start_t = convert(start_raw)
        end_t   = convert(end_raw)
    except:
        start_t = datetime.time(12, 0)
        end_t   = datetime.time(13, 0)

    tz = pytz.timezone("America/Denver")
    start_dt = tz.localize(datetime.datetime.combine(date, start_t))
    end_dt   = tz.localize(datetime.datetime.combine(date, end_t))

    return start_dt.isoformat(), end_dt.isoformat()

# ----------------------------------------------------------------------
import hashlib

def generate_event_id(row_number):
    # Stable unique ID generated from row number
    base = f"mixednuts-{row_number}"
    hash_part = hashlib.md5(base.encode()).hexdigest()[:6]   # small stable hash
    return f"mn-{row_number}-{hash_part}"


# ----------------------------------------------------------------------
def sync_events():
    sheets, calendar = load_google_services()

    # ----------------------------------------------------------------------
    # Banner
    # ----------------------------------------------------------------------
    print("\n" + "="*70)
    print("MIXED NUTS CALENDAR SYNC UTILITY")
    print("="*70)
    print("This script will:")
    print("  • Read the 'Mixed Nuts Current Remaining Schedule' Google Sheet")
    print("  • Filter rows by the date range you provide (FROM → TO)")
    print("  • For each row in that range:")
    print("        - Create or update a Google Calendar event")
    print("        - Set the start and end time")
    print("        - Set the event location")
    print("        - Put the Set name into the notes/description")
    print("  • Uses a stable event ID so re-running the script updates events")
    print("\nIMPORTANT:")
    print("  • This script NEVER deletes events — only adds or updates.")
    print("  • Make sure CALENDAR_ID is correct.")
    print("="*70 + "\n")

    # ----------------------------------------------------------------------
    # Date prompts
    # ----------------------------------------------------------------------
    print("Enter FROM date (MM/DD/YYYY):")
    from_date_str = input("> ").strip()

    print("Enter TO date (MM/DD/YYYY):")
    to_date_str = input("> ").strip()

    from_date = datetime.datetime.strptime(from_date_str, "%m/%d/%Y").date()
    to_date   = datetime.datetime.strptime(to_date_str, "%m/%d/%Y").date()

    print(f"\n🔄 Syncing events between {from_date} and {to_date}...\n")

    # ----------------------------------------------------------------------
    # Load sheet
    # ----------------------------------------------------------------------
    sheet = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=SHEET_RANGE
    ).execute()

    rows = sheet.get("values", [])
    if not rows:
        print("❌ No data found.")
        return

    header = rows[0]
    data_rows = rows[1:]

    # ----------------------------------------------------------------------
    # Process each row
    # ----------------------------------------------------------------------
    for idx, row in enumerate(data_rows, start=2):
        try:
            date_str = row[COL_DATE]
        except:
            continue

        try:
            row_date = datetime.datetime.strptime(date_str, "%m/%d/%Y").date()
        except:
            continue

        # Check range
        if not (from_date <= row_date <= to_date):
            continue

        # Extract fields
        try:
            time_str = row[COL_TIME]
            location = row[COL_LOCATION]
            set_name = row[COL_SET]
        except:
            continue

        # Parse times
        start_iso, end_iso = parse_time_range(date_str, time_str)

        # Build event
        event_id = generate_event_id(idx)
        event_body = {
            "summary": f"Mixed Nuts – {set_name}",
            "location": location,
            "description": f"Set: {set_name}",
            "start": {"dateTime": start_iso},
            "end":   {"dateTime": end_iso},
        }

        # ------------------------------------------------------------------
        # Create or update event using stable eventId
        # ------------------------------------------------------------------
        try:
            # Try to update existing event
            calendar.events().patch(
                calendarId=CALENDAR_ID,
                eventId=event_id,
                body=event_body
            ).execute()

            print(f"✅ Updated event {event_id} (row {idx})")

        except Exception:
            # Event does NOT exist → create it using insert() with custom ID
            new_event_body = {
                "id": event_id,   # <--- required for custom eventId
                **event_body
            }

            calendar.events().insert(
                calendarId=CALENDAR_ID,
                body=new_event_body
            ).execute()

            print(f"➕ Created event {event_id} (row {idx})")



    print("\n🎉 Sync complete!\n")

# ----------------------------------------------------------------------
if __name__ == "__main__":
    sync_events()
