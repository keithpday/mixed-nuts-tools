#BKT_SPREADSHEET_ID = "1q9chtQNZnO5QcDBaYTjnV0sITxo7zAvTHfLT7MkZybs"
#SCHED_SPREADSHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_booked_to_currentsched.py
───────────────────────────────────────────────────────────────────────────────
Audit BktDts vs CurrentYrSched, detect booked gigs not yet transferred,
and optionally append them interactively.

FEATURES:
  • Script-specific Google token file
  • Credentials loaded from ./config/credentials.json
  • Dynamic column detection (no A1:BK errors)
  • Date-range filtering (FROM/TO dates)
  • Interactive add: Y=add, N=skip, A=add all, Q=quit
  • Maps BktDts columns to CurrentYrSched columns A–S
"""

import os
import datetime
from typing import List, Dict, Optional, Tuple

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

#def list_sheet_names(service, sheet_id):
#    meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
#    print("\n### SHEET NAMES FOUND ###")
#    for s in meta["sheets"]:
#        print(f"- '{s['properties']['title']}'")
#    print("#########################\n")

# ─────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# REPLACE THESE with your real spreadsheet IDs
BKT_SPREADSHEET_ID = "1q9chtQNZnO5QcDBaYTjnV0sITxo7zAvTHfLT7MkZybs"
SCHED_SPREADSHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"

BKT_TAB_NAME   = "BkdDts"
SCHED_TAB_NAME = "CurrentYrSched"

# Mapping of column LETTERS in BktDts
BKT_COL = {
    "status":     "D",
    "day":        "AS",
    "date":       "AT",
    "venue":      "AU",
    "time":       "AV",
    "location":   "AW",
    "group":      "AX",
    "set":        "AY",
    "pays":       "AZ",
    "vocal":      "BA",
    "piano":      "BB",
    "bringkb":    "BC",
    "bass":       "BD",
    "drums":      "BE",
    "gtrvibes":   "BF",
    "special":    "BG",
    "revdate":    "BH",
    "notes":      "BI",
    "weekno":     "BJ",
    "nbrinband":  "BK",
}

# Mapping for CurrentYrSched (target sheet)
SCHED_COL = {
    "day":        "A",
    "date":       "B",
    "venue":      "C",
    "time":       "D",
    "location":   "E",
    "group":      "F",
    "set":        "G",
    "pays":       "H",
    "vocal":      "I",
    "piano":      "J",
    "bringkb":    "K",
    "bass":       "L",
    "drums":      "M",
    "gtr":        "N",
    "vibes":      "O",
    "revdate":    "P",
    "notes":      "Q",
    "weekno":     "R",
    "nbrinband":  "S",
}


# ─────────────────────────────────────────────────────────────────────
# UTILITY FUNCTIONS
# ─────────────────────────────────────────────────────────────────────

def col_letter_to_index(col: str) -> int:
    """Convert an A1-style column letter (e.g. 'A', 'AS') to a 0-based index."""
    col = col.upper()
    result = 0
    for ch in col:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def get_cell(row: List[str], idx: int) -> str:
    """Safely get a cell by index."""
    if idx < len(row):
        return str(row[idx]).strip()
    return ""


def parse_sheet_date(v: str) -> Optional[datetime.date]:
    if not v:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(v, fmt).date()
        except ValueError:
            pass
    return None


def build_key(date_obj: datetime.date, time_str: str, venue: str, group: str) -> str:
    """Normalize a unique event key."""
    return f"{date_obj.isoformat()}|{time_str.strip().upper()}|{venue.strip().upper()}|{group.strip().upper()}"


# ─────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS SERVICE
# ─────────────────────────────────────────────────────────────────────

def get_sheets_service():
    """Authenticate with Google Sheets using script-specific token."""
    script_dir  = os.path.abspath(os.path.dirname(__file__))
    script_name = os.path.splitext(os.path.basename(__file__))[0]

    token_path = os.path.join(script_dir, f"{script_name}_token.json")
    creds_path = os.path.join(script_dir, "config", "credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(f"Missing credentials.json at:\n{creds_path}")
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("sheets", "v4", credentials=creds)


# ─────────────────────────────────────────────────────────────────────
# SHEET LOADING WITH DYNAMIC COLUMN DETECTION
# ─────────────────────────────────────────────────────────────────────

def detect_last_col_letter() -> str:
    """Return a generous upper column limit. Google Sheets will return actual data."""
    return "ZZ"   # wide enough for ~700 columns



def load_sheet(service, sheet_id: str, tab_name: str) -> List[List[str]]:
    """
    Load rows from a sheet using a wide-enough range.
    Google Sheets safely returns only real data.
    """
    rng = f"{tab_name}!A1:ZZ"
    resp = service.spreadsheets().values().get(
        spreadsheetId=sheet_id,
        range=rng
    ).execute()
    return resp.get("values", [])



# ─────────────────────────────────────────────────────────────────────
# BUILD EVENT KEY SET FOR CurrentYrSched
# ─────────────────────────────────────────────────────────────────────

def build_sched_keyset(rows: List[List[str]], cm: Dict[str, int]) -> set:
    keys = set()
    for row in rows:
        d = parse_sheet_date(get_cell(row, cm["date"]))
        if not d:
            continue
        key = build_key(
            d,
            get_cell(row, cm["time"]),
            get_cell(row, cm["venue"]),
            get_cell(row, cm["group"]),
        )
        keys.add(key)
    return keys


# ─────────────────────────────────────────────────────────────────────
# MAPPING BktDts → CurrentYrSched ROW
# ─────────────────────────────────────────────────────────────────────

def make_sched_row(br: List[str], b: Dict[str,int], s: Dict[str,int]) -> List[str]:
    """Create a new CurrentYrSched row from a BktDts row."""

    # Target row size = number of mapped columns
    max_idx = max(s.values())
    row = [""] * (max_idx + 1)

    def map_field(dst_key, src_key):
        row[s[dst_key]] = get_cell(br, b[src_key])

    map_field("day",        "day")
    map_field("date",       "date")
    map_field("venue",      "venue")
    map_field("time",       "time")
    map_field("location",   "location")
    map_field("group",      "group")
    map_field("set",        "set")
    map_field("pays",       "pays")
    map_field("vocal",      "vocal")
    map_field("piano",      "piano")
    map_field("bringkb",    "bringkb")
    map_field("bass",       "bass")
    map_field("drums",      "drums")

    # Guitar/Vibes split
    row[s["gtr"]]   = get_cell(br, b["gtrvibes"])
    row[s["vibes"]] = get_cell(br, b["special"])

    map_field("revdate",    "revdate")
    map_field("notes",      "notes")
    map_field("weekno",     "weekno")
    map_field("nbrinband",  "nbrinband")

    return row


# ─────────────────────────────────────────────────────────────────────
# APPEND ROW TO CurrentYrSched
# ─────────────────────────────────────────────────────────────────────

def append_sched(service, row: List[str]):
    rng = f"{SCHED_TAB_NAME}!A:S"
    body = {"values": [row]}
    service.spreadsheets().values().append(
        spreadsheetId=SCHED_SPREADSHEET_ID,
        range=rng,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body
    ).execute()


# ─────────────────────────────────────────────────────────────────────
# MAIN AUDIT PROCESS
# ─────────────────────────────────────────────────────────────────────

def run_audit():

    service = get_sheets_service()
    #list_sheet_names(service, BKT_SPREADSHEET_ID)
    
    print("\nMixed Nuts Booking Audit – BktDts vs CurrentYrSched")
    print("Only rows with Booking Status = 'Booked' will be considered.\n")

    # Date filter input
    f_str = input("FROM date (YYYY-MM-DD, blank = none): ").strip()
    t_str = input("TO date   (YYYY-MM-DD, blank = none): ").strip()

    from_date = datetime.date.fromisoformat(f_str) if f_str else None
    to_date   = datetime.date.fromisoformat(t_str) if t_str else None

    print("\nLoading sheets...")

    bkt_values  = load_sheet(service, BKT_SPREADSHEET_ID, BKT_TAB_NAME)
    sched_values = load_sheet(service, SCHED_SPREADSHEET_ID, SCHED_TAB_NAME)

    if not bkt_values:
        print("ERROR: BktDts sheet is empty.")
        return
    if not sched_values:
        print("ERROR: CurrentYrSched sheet is empty.")
        return

    bkt_header, bkt_rows       = bkt_values[0],  bkt_values[1:]
    sched_header, sched_rows   = sched_values[0], sched_values[1:]

    # Build column index maps
    b = {k: col_letter_to_index(v) for k, v in BKT_COL.items()}
    s = {k: col_letter_to_index(v) for k, v in SCHED_COL.items()}

    # Build existing schedule keyset
    sched_keys = build_sched_keyset(sched_rows, s)

    add_all = False
    added = 0
    skipped = 0
    missing = 0

    print("\nStarting audit...\n")

    for br in bkt_rows:

        if get_cell(br, b["status"]) != "Booked":
            continue

        date_obj = parse_sheet_date(get_cell(br, b["date"]))
        if not date_obj:
            continue

        if from_date and date_obj < from_date:
            continue
        if to_date and date_obj > to_date:
            continue

        time_str = get_cell(br, b["time"])
        venue    = get_cell(br, b["venue"])
        group    = get_cell(br, b["group"])

        key = build_key(date_obj, time_str, venue, group)
        if key in sched_keys:
            continue

        missing += 1

        summary = f"""
MISSING SCHEDULE ENTRY FOUND:
  Date : {get_cell(br, b["date"])}
  Day  : {get_cell(br, b["day"])}
  Time : {time_str}
  Venue: {venue}
  Group: {group}
  Notes: {get_cell(br, b["notes"])}
"""

        print(summary)

        if add_all:
            new_row = make_sched_row(br, b, s)
            append_sched(service, new_row)
            sched_keys.add(key)
            added += 1
            continue

        choice = input("ADD THIS EVENT? (Y=add, N=skip, A=add all, Q=quit): ").strip().upper()

        if choice == "Q":
            print("\nStopping audit at user request.\n")
            break
        elif choice == "A":
            add_all = True
            new_row = make_sched_row(br, b, s)
            append_sched(service, new_row)
            sched_keys.add(key)
            added += 1
        elif choice == "Y":
            new_row = make_sched_row(br, b, s)
            append_sched(service, new_row)
            sched_keys.add(key)
            added += 1
        else:
            skipped += 1

    print("\nAUDIT COMPLETE")
    print(f"  Missing events encountered : {missing}")
    print(f"  Added to CurrentYrSched    : {added}")
    print(f"  Skipped                    : {skipped}\n")


if __name__ == "__main__":
    run_audit()
    #input("\nPress Enter to close...")

