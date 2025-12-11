#!/usr/bin/env python3

"""
calendar_sync_utility_v2.py

Syncs the "Mixed Nuts Current Remaining Schedule" Google Sheet
to a specific Google Calendar, for a date range you choose.

For each date in the range:
  1. Deletes ONLY events that have the hidden tag:
       extendedProperties.private.sync_tag == "Created by Calendar Sync Utility"
  2. Inserts fresh events from the sheet for that date.

Event behavior:
  - Title (summary): Venue name (Column C)
        If the Set (Column F) contains "duo" (case-insensitive),
        " (DUO)" is appended to the title.
  - Description: Set name only (Column F)
  - Location: Column E
  - Time: parsed from Column D (e.g., "6:00 p - 8:00 p")
  - Timezone: America/Denver
  - Hidden tag: stored in extendedProperties.private["sync_tag"]
"""

import datetime
from pathlib import Path

import pytz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------

SPREADSHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SHEET_RANGE = "CurrentYrSched!A:Z"

# Your Mixed Nuts Google Calendar ID
CALENDAR_ID = "appsoni.com_dump9u7hsmk3tj5dt82u2tesj0@group.calendar.google.com"

# Hidden tag used to identify events created by this script
SYNC_TAG = "Created by Calendar Sync Utility"

# Column indexes (zero-based in the row list from Sheets API)
COL_DATE = 1       # Column B - Date (MM/DD/YYYY)
COL_VENUE = 2      # Column C - Venue name
COL_TIME = 3       # Column D - Time range "6:00 p - 8:00 p"
COL_LOCATION = 4   # Column E - Address / Location
COL_SET = 5        # Column F - Set name

TIMEZONE = "America/Denver"

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
    SCRIPT_NAME = "calendar_sync_utility_v2"  # name to use for token file

    BASE_CONFIG_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config"

    CREDENTIALS_PATH = f"{BASE_CONFIG_PATH}/credentials.json"
    TOKEN_PATH = f"{BASE_CONFIG_PATH}/{SCRIPT_NAME}_token.json"

    creds = None

    # Load existing token (if present)
    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If no valid token, run OAuth flow
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
        creds = flow.run_local_server(port=0)

        # Save token under script-specific name
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    # Build service clients
    sheets = build("sheets", "v4", credentials=creds)
    calendar = build("calendar", "v3", credentials=creds)
    return sheets, calendar


# ----------------------------------------------------------------------
def parse_time_range(date_str, time_range_str):
    """
    Convert a date and time range string into RFC3339 datetime strings.

    date_str: "12/5/2026"
    time_range_str: "6:00 p - 8:00 p"

    Returns: (start_iso, end_iso)
    """

    date = datetime.datetime.strptime(date_str, "%m/%d/%Y").date()

    def convert(t):
        t = t.strip().lower().replace(" ", "")
        # Expect something like "6:00p" or "10:30a"
        if t.endswith("p"):
            base = datetime.datetime.strptime(t[:-1], "%I:%M")
            # 12-hour offset for PM unless it's 12 PM already
            if base.hour != 12:
                base = base + datetime.timedelta(hours=12)
            return base.time()
        elif t.endswith("a"):
            base = datetime.datetime.strptime(t[:-1], "%I:%M")
            # 12 AM is 00:xx
            if base.hour == 12:
                base = base.replace(hour=0)
            return base.time()
        else:
            # Fallback: assume HH:MM 24-hour
            return datetime.datetime.strptime(t, "%H:%M").time()

    try:
        start_raw, end_raw = time_range_str.split("-")
        start_t = convert(start_raw)
        end_t = convert(end_raw)
    except Exception:
        # Default 1-hour noon event if parsing fails
        start_t = datetime.time(12, 0)
        end_t = datetime.time(13, 0)

    tz = pytz.timezone(TIMEZONE)
    start_dt = tz.localize(datetime.datetime.combine(date, start_t))
    end_dt = tz.localize(datetime.datetime.combine(date, end_t))

    return start_dt.isoformat(), end_dt.isoformat()


# ----------------------------------------------------------------------
def get_date_window(dt):
    """
    Given a date (datetime.date), return (timeMin_iso, timeMax_iso)
    covering that date in the configured timezone.
    """
    tz = pytz.timezone(TIMEZONE)
    start_dt = tz.localize(datetime.datetime.combine(dt, datetime.time.min))
    end_dt = tz.localize(datetime.datetime.combine(dt + datetime.timedelta(days=1),
                                                   datetime.time.min))
    return start_dt.isoformat(), end_dt.isoformat()


# ----------------------------------------------------------------------
def sync_events():
    sheets, calendar = load_google_services()

    # ----------------------------------------------------------------------
    # Banner
    # ----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("MIXED NUTS CALENDAR SYNC UTILITY  (v2)")
    print("=" * 70)
    print("This script will:")
    print("  • Read the 'Mixed Nuts Current Remaining Schedule' Google Sheet")
    print("  • Filter rows by the date range you provide (FROM → TO)")
    print("  • For each date in that range:")
    print("        - Delete calendar events tagged by this utility")
    print("        - Insert fresh events from the sheet for that date")
    print("  • Uses a hidden metadata tag in extendedProperties.private.sync_tag")
    print("    with value 'Created by Calendar Sync Utility' to identify events.")
    print("\nIMPORTANT:")
    print("  • This script ONLY deletes events it created (with the hidden tag).")
    print("  • Other events on this calendar are left untouched.")
    print("  • Description is the Set name only; title is the Venue,")
    print("    and '(DUO)' is appended if the Set contains the word 'Duo'.")
    print("=" * 70 + "\n")

    # ----------------------------------------------------------------------
    # Date prompts
    # ----------------------------------------------------------------------
    print("Enter FROM date (MM/DD/YYYY):")
    from_date_str = input("> ").strip()

    print("Enter TO date (MM/DD/YYYY):")
    to_date_str = input("> ").strip()

    from_date = datetime.datetime.strptime(from_date_str, "%m/%d/%Y").date()
    to_date = datetime.datetime.strptime(to_date_str, "%m/%d/%Y").date()

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
        print("❌ No data found in sheet.")
        return

    header = rows[0]
    data_rows = rows[1:]

    # ----------------------------------------------------------------------
    # Collect entries from the sheet within the date range
    # ----------------------------------------------------------------------
    entries = []
    for idx, row in enumerate(data_rows, start=2):
        try:
            date_str = row[COL_DATE]
        except Exception:
            continue

        try:
            row_date = datetime.datetime.strptime(date_str, "%m/%d/%Y").date()
        except Exception:
            continue

        # Filter by date range
        if not (from_date <= row_date <= to_date):
            continue

        # Extract the other fields; skip if missing
        try:
            venue = row[COL_VENUE]
            time_str = row[COL_TIME]
            location = row[COL_LOCATION]
            set_name = row[COL_SET]
        except Exception:
            continue

        entries.append({
            "row_idx": idx,
            "date": row_date,
            "date_str": date_str,
            "venue": venue,
            "time_str": time_str,
            "location": location,
            "set_name": set_name,
        })

    if not entries:
        print("ℹ️  No rows in the sheet matched the given date range.")
        return

    # Build a sorted list of unique dates that had entries
    unique_dates = sorted({e["date"] for e in entries})

    # ----------------------------------------------------------------------
    # Process each date: delete tagged events, then insert fresh ones
    # ----------------------------------------------------------------------
    for d in unique_dates:
        print(f"📅 Processing date: {d}")

        # 1) DELETE PHASE
        time_min, time_max = get_date_window(d)
        deleted_count = 0

        page_token = None
        while True:
            events_result = calendar.events().list(
                calendarId=CALENDAR_ID,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                pageToken=page_token
            ).execute()

            for event in events_result.get("items", []):
                extended = event.get("extendedProperties", {})
                private_props = extended.get("private", {})
                tag = private_props.get("sync_tag")

                if tag == SYNC_TAG:
                    # Delete this event
                    calendar.events().delete(
                        calendarId=CALENDAR_ID,
                        eventId=event["id"]
                    ).execute()
                    deleted_count += 1

            page_token = events_result.get("nextPageToken")
            if not page_token:
                break

        print(f"   🗑  Deleted {deleted_count} existing tagged event(s).")

        # 2) INSERT PHASE
        day_entries = [e for e in entries if e["date"] == d]
        inserted_count = 0

        for e in day_entries:
            # Build title/summary
            set_lower = e["set_name"].lower()
            summary = e["venue"]
            if "duo" in set_lower:
                summary = f"{summary} (DUO)"

            # Parse times
            start_iso, end_iso = parse_time_range(e["date_str"], e["time_str"])

            event_body = {
                "summary": summary,
                "location": e["location"],
                "description": e["set_name"],  # Set only
                "start": {"dateTime": start_iso},
                "end": {"dateTime": end_iso},
                "extendedProperties": {
                    "private": {
                        "sync_tag": SYNC_TAG
                    }
                },
            }

            calendar.events().insert(
                calendarId=CALENDAR_ID,
                body=event_body
            ).execute()
            inserted_count += 1

        print(f"   ➕ Inserted {inserted_count} new event(s) for {d}.\n")

    print("\n🎉 Sync complete!\n")


# ----------------------------------------------------------------------
if __name__ == "__main__":
    sync_events()
