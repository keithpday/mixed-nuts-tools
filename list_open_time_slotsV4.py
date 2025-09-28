#!/usr/bin/env python3
"""
List daily availability windows (true time ranges) from a Google Sheets schedule.

Rules:
- Playable day window: 9:00 am → 9:00 pm (local).
- Enforce 2-hour separation around *every* scheduled gig:
  For each gig, block [ gig_start - 2h , gig_end + 2h ].
- The day's available windows are the complement of all blocked intervals within 9:00–21:00.
- Exclude Sundays, New Year's Day (Jan 1), and Christmas (Dec 25).

Sheet:
- Tab: CurrentYrSched
- Required columns: Date, Venue, Location, Time
- Time format: "hh:mm a/p(m optional) - hh:mm a/p(m optional)"
  e.g., "3:00 p - 4:30 p", "1:30 pm - 3:00 pm"

Prompts:
- Start date (default: today)
- End date   (default: today + 60 days)
- Optional CSV path

Output:
- One line per eligible date: YYYY-MM-DD (Dow): <availability ranges or "No availability">
- CSV (if chosen): Date, DayOfWeek, AvailableRanges
"""

import re
import textwrap
from datetime import datetime, date, timedelta
from collections import defaultdict

import gspread
from google.oauth2.service_account import Credentials

# ---------------- CONFIG ----------------
SERVICE_ACCOUNT_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
SHEET_ID             = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB         = "CurrentYrSched"

COL_DATE     = "Date"
COL_VENUE    = "Venue"
COL_LOCATION = "Location"
COL_TIME     = "Time"

# Skip Sundays and these fixed-date holidays
HOLIDAYS_MMDD = {(1, 1), (12, 25)}  # New Year's Day, Christmas

# Daily playable window (minutes since midnight)
DAY_START_MIN = 9 * 60      # 09:00
DAY_END_MIN   = 21 * 60     # 21:00

# Buffer before and after each gig (minutes)
BUFFER_MIN = 120            # 2 hours

# Strict time range parser: "hh:mm a/p(m?) - hh:mm a/p(m?)"
_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*[-–—]\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*$"
)

# ---------------- Helpers ----------------
def print_banner():
    banner = textwrap.dedent(__doc__ or "").strip()
    if banner:
        line = "=" * 72
        print(f"\n{line}\n{banner}\n{line}\n")

def is_blocked_date(d: date) -> bool:
    """True if the date should be excluded (Sunday or fixed holiday)."""
    return d.weekday() == 6 or (d.month, d.day) in HOLIDAYS_MMDD  # Sunday = 6

def _to_minutes(h: int, m: int, ap: str) -> int:
    """Convert hour/min + 'a'/'p'/'am'/'pm' to minutes since midnight."""
    ap = ap.lower()
    if ap.startswith("a"):  # AM
        h = 0 if h == 12 else h
    else:                   # PM
        h = 12 if h == 12 else h + 12
    return h * 60 + m

def parse_time_range_strict(text: str) -> tuple[int | None, int | None]:
    """Parse 'hh:mm a/p(m?) - hh:mm a/p(m?)' into (start_min, end_min)."""
    if not text:
        return (None, None)
    s = str(text).strip().replace("—", "-").replace("–", "-")
    m = _TIME_RANGE_RE.match(s)
    if not m:
        return (None, None)
    sh, sm, sap, eh, em, eap = m.groups()
    start_min = _to_minutes(int(sh), int(sm), sap)
    end_min   = _to_minutes(int(eh), int(em), eap)
    return (start_min, end_min)

def parse_sheet_date(raw) -> date | None:
    """Parse a Sheets date cell into a Python date."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%-m/%-d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    # Excel/Sheets serial (days since 1899-12-30)
    if s.isdigit():
        base = date(1899, 12, 30)
        try:
            return base + timedelta(days=int(s))
        except Exception:
            return None
    return None

def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)

def format_minutes(mins: int) -> str:
    """Return 'h:mm am/pm' (lowercase, no leading zero)."""
    h24 = mins // 60
    m = mins % 60
    ap = "am" if h24 < 12 else "pm"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d} {ap}"

def complement_within_day(blocked_intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """
    Given a list of *blocked* intervals (minutes since midnight), return the
    list of available intervals within [DAY_START_MIN, DAY_END_MIN].
    Intervals are half-open [start, end).
    """
    day_start, day_end = DAY_START_MIN, DAY_END_MIN
    if day_start >= day_end:
        return []

    # Clip blocked intervals to day window; drop empty/invalid ranges
    clipped = []
    for s, e in blocked_intervals:
        s = max(s, day_start)
        e = min(e, day_end)
        if e > s:
            clipped.append((s, e))

    # Merge overlapping/adjacent blocked intervals
    clipped.sort()
    merged = []
    for s, e in clipped:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    # Complement: gaps between merged blocks
    avail = []
    cur = day_start
    for s, e in merged:
        if s > cur:
            avail.append((cur, s))
        cur = max(cur, e)
    if cur < day_end:
        avail.append((cur, day_end))
    # If there were no blocks, whole day is available
    if not merged and not avail:
        avail = [(day_start, day_end)]
    return avail

def prompt_user_options() -> tuple[date, date, str | None]:
    """Prompt for start/end dates and an optional CSV path, with sensible defaults."""
    today = date.today()
    default_start = today
    default_end = today + timedelta(days=60)

    def _ask_date(prompt_text: str, default_val: date) -> date:
        s = input(f"{prompt_text} [default {default_val.isoformat()}]: ").strip()
        if not s:
            return default_val
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            print("  ⚠️ Invalid date format (use YYYY-MM-DD). Using default.")
            return default_val

    start_date = _ask_date("Start date (YYYY-MM-DD)", default_start)
    end_date   = _ask_date("End date   (YYYY-MM-DD)", default_end)

    if end_date < start_date:
        print("  ⚠️ End date precedes start date — swapping them.")
        start_date, end_date = end_date, start_date

    csv_path = None
    choice = input("Write CSV output? [y/N]: ").strip().lower()
    if choice == "y":
        suggested = f"/home/keith/Desktop/availability_{start_date}_{end_date}.csv"
        p = input(f"CSV path [default {suggested}]: ").strip()
        csv_path = p or suggested

    return start_date, end_date, csv_path

# ---------------- Core ----------------
def collect_blocked_intervals_by_date(rows, start_date: date, end_date: date) -> dict[date, list[tuple[int, int]]]:
    """
    Build {date: [(blocked_start, blocked_end), ...]} where each blocked interval is:
        [ gig_start - BUFFER_MIN , gig_end + BUFFER_MIN ]
    """
    blocked = defaultdict(list)
    for row in rows:
        d = parse_sheet_date(row.get(COL_DATE))
        if not d or d < start_date or d > end_date:
            continue
        if is_blocked_date(d):
            continue

        tcell = str(row.get(COL_TIME, "") or "").strip()
        start_min, end_min = parse_time_range_strict(tcell)
        if start_min is None or end_min is None:
            # Can't parse -> ignore this gig (change here if you want unknown to block).
            continue

        start_with_buffer = start_min - BUFFER_MIN
        end_with_buffer   = end_min + BUFFER_MIN
        blocked[d].append((start_with_buffer, end_with_buffer))
    return blocked

def main():
    print_banner()
    # Prompt first
    start_date, end_date, csv_path = prompt_user_options()

    # Auth + read sheet
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(SCHEDULE_TAB)
    rows = ws.get_all_records()

    # Build blocked intervals per date from rows
    blocked_by_date = collect_blocked_intervals_by_date(rows, start_date, end_date)

    print(f"\n=== Availability (excluding Sundays, Jan 1, Dec 25) {start_date} → {end_date} ===\n")
    availability_rows = []
    any_output = False

    for d in daterange(start_date, end_date):
        if is_blocked_date(d):
            continue

        blocked = blocked_by_date.get(d, [])
        avail = complement_within_day(blocked)

        if not avail:
            line = f"{d.isoformat()} ({d.strftime('%a')}): No availability"
            print(line)
            availability_rows.append((d.isoformat(), d.strftime('%a'), ""))
            continue

        pieces = [f"{format_minutes(s)}–{format_minutes(e)}" for s, e in avail]
        joined = ", ".join(pieces)
        line = f"{d.isoformat()} ({d.strftime('%a')}): {joined}"
        print(line)
        availability_rows.append((d.isoformat(), d.strftime('%a'), joined))
        any_output = True

    if not any_output:
        print("No availability in this window.")

    if csv_path:
        try:
            import csv
            with open(csv_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["Date", "DayOfWeek", "AvailableRanges"])
                w.writerows(availability_rows)
            print(f"\nCSV written to: {csv_path}")
        except Exception as e:
            print(f"\n⚠️ CSV write failed: {e}")

if __name__ == "__main__":
    main()
