#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
availability_calendar_email_v5.py
───────────────────────────────────────────────────────────────────────────────
Generates an HTML month-view availability calendar based on Google Sheets
schedule, then emails it to:

    keith.day@legacyperformers.org

You can then forward or edit the email before sending to venues.

Features:
- Uses CurrentYrSched tab
- Columns: Date, Venue, Location, Time, Set
- Time format: "1:30 pm - 3:00 pm"
- Skips Sundays, Jan 1, Dec 25
- Optional skip of Wednesdays (prompted)
- Travel buffer based on:
    * Requesting venue county
    * Gig county
    * Selected ensemble:
        Mixed Nuts (5-piece):
            - same county → 3 hours
            - SL ↔ outside → 4 hours
            - outside ↔ outside (different) → 5 hours
        Mixed Nuts Duo:
            - same county → 2 hours
            - SL ↔ outside → 3 hours
            - outside ↔ outside (different) → 4 hours
- Counties inferred from Location via keyword mapping; if unknown, prompted once
  and cached in a JSON file.
- Prompts for requested show length in whole hours (default = 1).
- Availability windows shown only if they are at least that long.
- Ensemble selection:
    - Mixed Nuts (5-piece)
    - Mixed Nuts Duo
  Each uses only its own gigs (Duo gigs do not block Mixed Nuts, and vice versa).
- Subject line includes ensemble name and dates in MM/DD/YYYY.
- Sends HTML email with calendar to Keith for review.
"""

import re
import json
import calendar
from datetime import date, datetime, timedelta
from collections import defaultdict
from html import escape
from pathlib import Path

import gspread
import pandas as pd

from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build
from base64 import urlsafe_b64encode
from google.auth.transport.requests import Request as GARequest
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError


# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
SHEET_ID        = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB    = "CurrentYrSched"

CREDS_PATH        = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
TOKEN_PATH        = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.json"
COUNTY_CACHE_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/county_cache.json"

SEND_TO = "keith.day@legacyperformers.org"

DAY_START_MIN = 9 * 60   # 9:00
DAY_END_MIN   = 21 * 60  # 21:00
HOLIDAYS_MMDD = {(1, 1), (12, 25)}

# Canonical county names we’ll use internally
COUNTY_SALT_LAKE = "Salt Lake"
VALID_COUNTIES = {
    "sl": COUNTY_SALT_LAKE,
    "saltlake": COUNTY_SALT_LAKE,
    "salt lake": COUNTY_SALT_LAKE,
    "salt lake county": COUNTY_SALT_LAKE,
    "utah": "Utah",
    "utah county": "Utah",
    "davis": "Davis",
    "davis county": "Davis",
    "weber": "Weber",
    "weber county": "Weber",
    "summit": "Summit",
    "summit county": "Summit",
    "tooele": "Tooele",
    "tooele county": "Tooele",
    "wasatch": "Wasatch",
    "wasatch county": "Wasatch",
    "washington": "Washington",
    "washington county": "Washington",
    "other": "Other",
}

# City/area keyword mapping to county (simple substring match, lowercased)
CITY_TO_COUNTY = {
    # Salt Lake County
    "salt lake city": COUNTY_SALT_LAKE,
    "slc": COUNTY_SALT_LAKE,
    "west jordan": COUNTY_SALT_LAKE,
    "south jordan": COUNTY_SALT_LAKE,
    "murray": COUNTY_SALT_LAKE,
    "sandy": COUNTY_SALT_LAKE,
    "draper": COUNTY_SALT_LAKE,
    "holladay": COUNTY_SALT_LAKE,
    "cottonwood heights": COUNTY_SALT_LAKE,
    "taylorsville": COUNTY_SALT_LAKE,
    "riverton": COUNTY_SALT_LAKE,
    "herriman": COUNTY_SALT_LAKE,
    "kearns": COUNTY_SALT_LAKE,
    "magna": COUNTY_SALT_LAKE,
    "midvale": COUNTY_SALT_LAKE,
    "millcreek": COUNTY_SALT_LAKE,

    # Utah County
    "provo": "Utah",
    "orem": "Utah",
    "lehi": "Utah",
    "american fork": "Utah",
    "saratoga springs": "Utah",
    "pleasant grove": "Utah",
    "lindon": "Utah",
    "vineyard": "Utah",
    "spanish fork": "Utah",
    "mapleton": "Utah",

    # Davis County
    "bountiful": "Davis",
    "woods cross": "Davis",
    "centerville": "Davis",
    "farmington": "Davis",
    "kaysville": "Davis",
    "layton": "Davis",
    "clearfield": "Davis",
    "syracuse": "Davis",

    # Weber County
    "ogden": "Weber",
    "north ogden": "Weber",
    "south ogden": "Weber",
    "roy": "Weber",
    "pleasant view": "Weber",

    # Summit County
    "park city": "Summit",
    "kamas": "Summit",
    "coalville": "Summit",

    # Tooele County
    "tooele": "Tooele",
    "stansbury": "Tooele",   # Stansbury Park
    "grantsville": "Tooele",
    "erda": "Tooele",

    # Wasatch County
    "heber": "Wasatch",
    "midway": "Wasatch",
    "charleston": "Wasatch",

    # Washington County
    "st. george": "Washington",
    "st george": "Washington",
    "washington, ut": "Washington",
    "hurricane": "Washington",
    "santa clara": "Washington",
    "ivins": "Washington",
}


# ──────────────────────────────────────────────────────────────────────────────
# BASIC HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def is_blocked_date(d: date, block_wednesdays: bool) -> bool:
    """Determine whether a date should be excluded from availability."""

    # Always block Sundays
    if d.weekday() == 6:  # Sunday
        return True

    # Always block New Year's Day, Christmas Eve, Christmas Day
    if (d.month, d.day) in {(1, 1), (12, 24), (12, 25)}:
        return True

    # Block Thanksgiving: 4th Thursday of November
    if d.month == 11 and d.weekday() == 3:  # Thursday == 3
        # 4th Thursday always falls between Nov 22–28
        if 22 <= d.day <= 28:
            return True

    # Block Wednesdays unless it's Veterans Day (Nov 11)
    if block_wednesdays and d.weekday() == 2:  # Wednesday
        # Exception: Veterans Day (Nov 11)
        if not (d.month == 11 and d.day == 11):
            return True

    return False




def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _to_minutes(h: int, m: int, ap: str) -> int:
    ap = ap.lower()
    if ap.startswith("a"):
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return h * 60 + m


_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*[-–]\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*$"
)


def parse_time_range(text: str):
    if not text:
        return (None, None)
    t = text.replace("—", "-").replace("–", "-")
    m = _TIME_RANGE_RE.match(t)
    if not m:
        return (None, None)
    sh, sm, sap, eh, em, eap = m.groups()
    return _to_minutes(int(sh), int(sm), sap), _to_minutes(int(eh), int(em), eap)


def parse_sheet_date(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        ts = pd.to_datetime(raw, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.date()
    except Exception:
        return None


def complement_within_day(blocked):
    """Given blocked intervals, return available intervals within the day window."""
    day_start, day_end = DAY_START_MIN, DAY_END_MIN
    clipped = []
    for s, e in blocked:
        s = max(s, day_start)
        e = min(e, day_end)
        if e > s:
            clipped.append((s, e))
    clipped.sort()

    merged = []
    for s, e in clipped:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    avail = []
    cur = day_start
    for s, e in merged:
        if s > cur:
            avail.append((cur, s))
        cur = max(cur, e)

    if cur < day_end:
        avail.append((cur, day_end))

    if not merged and not avail:
        avail = [(day_start, day_end)]

    return avail


def format_minutes(m: int) -> str:
    h24 = m // 60
    mins = m % 60
    ap = "am" if h24 < 12 else "pm"
    h12 = h24 % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{mins:02d} {ap}"


# ──────────────────────────────────────────────────────────────────────────────
# COUNTY HELPERS & BUFFER LOGIC
# ──────────────────────────────────────────────────────────────────────────────

def load_county_cache() -> dict:
    p = Path(COUNTY_CACHE_PATH)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_county_cache(cache: dict) -> None:
    p = Path(COUNTY_CACHE_PATH)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalize_location_key(loc: str) -> str:
    return (loc or "").strip().lower()


def infer_county_from_location_text(loc: str) -> str | None:
    """Try to infer county from Location string using CITY_TO_COUNTY mapping."""
    s = (loc or "").strip().lower()
    if not s:
        return None
    for key, county in CITY_TO_COUNTY.items():
        if key in s:
            return county
    return None


def parse_county_input(raw: str, default: str | None = None) -> str | None:
    s = (raw or "").strip().lower()
    if not s and default:
        return default
    return VALID_COUNTIES.get(s, None)


def prompt_for_county(loc: str, default_county: str = COUNTY_SALT_LAKE) -> str:
    print("\nUnable to determine county for location:")
    print(f"   \"{loc}\"")
    print("Please enter county code (one of):")
    print("   SL / Utah / Davis / Weber / Summit / Tooele / Wasatch / Washington / Other")
    prompt = f"County [default {default_county}]: "
    while True:
        ans = input(prompt)
        county = parse_county_input(ans, default=default_county)
        if county:
            return county
        print("  ⚠️ Unrecognized entry. Please try again.")


def get_gig_county(location: str, county_cache: dict, default_for_prompt: str) -> str:
    """Determine county for a gig location, using cache, mapping, and prompting."""
    key = normalize_location_key(location)
    if key in county_cache:
        return county_cache[key]

    # Try automatic mapping
    auto = infer_county_from_location_text(location)
    if auto:
        county_cache[key] = auto
        return auto

    # Prompt user
    county = prompt_for_county(location, default_county=default_for_prompt)
    county_cache[key] = county
    return county


def compute_buffer_minutes(requester_county: str, gig_county: str, ensemble: str) -> int:
    """Compute travel buffer in minutes based on requester vs. gig county and ensemble.

    For Mixed Nuts (ensemble == "M"):
        - same county → 3 hours
        - SL ↔ outside → 4 hours
        - outside ↔ outside (different) → 5 hours

    For Mixed Nuts Duo (ensemble == "D"):
        - same county → 2 hours
        - SL ↔ outside → 3 hours
        - outside ↔ outside (different) → 4 hours
    """
    r = requester_county
    g = gig_county

    # Conservative fallback if something is missing
    if not r or not g:
        return 4 * 60

    if r == g:
        hours = 3 if ensemble == "M" else 2
    elif r == COUNTY_SALT_LAKE or g == COUNTY_SALT_LAKE:
        hours = 4 if ensemble == "M" else 3
    else:
        hours = 5 if ensemble == "M" else 4

    return hours * 60


# ──────────────────────────────────────────────────────────────────────────────
# COLLECT BLOCKED INTERVALS FROM GOOGLE SHEET
# ──────────────────────────────────────────────────────────────────────────────

def collect_blocked(start_date: date,
                    end_date: date,
                    requester_county: str,
                    block_wednesdays: bool,
                    county_cache: dict,
                    ensemble: str) -> dict[date, list[tuple[int, int]]]:
    """
    Build blocked intervals per date using per-gig travel buffers.

    Ensemble filtering:
        - If ensemble == "M": use only gigs whose Set does NOT contain "duo"
        - If ensemble == "D": use only gigs whose Set DOES contain "duo"
    """
    gc = gspread.authorize(
        ServiceAccountCredentials.from_service_account_file(
            SERVICE_ACCOUNT,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
        )
    )
    ws = gc.open_by_key(SHEET_ID).worksheet(SCHEDULE_TAB)
    rows = ws.get_all_records()

    blocked_by_date: dict[date, list[tuple[int, int]]] = defaultdict(list)

    for r in rows:
        d = parse_sheet_date(r.get("Date"))
        if not d or d < start_date or d > end_date:
            continue
        if is_blocked_date(d, block_wednesdays):
            continue

        # Filter by ensemble based on the Set column
        set_text = str(r.get("Set", "") or "")
        is_duo_gig = "duo" in set_text.lower()

        if ensemble == "M" and is_duo_gig:
            continue  # skip duo gigs when looking for Mixed Nuts availability
        if ensemble == "D" and not is_duo_gig:
            continue  # skip non-duo gigs when looking for Duo availability

        t = r.get("Time", "")
        smin, emin = parse_time_range(str(t))
        if smin is None or emin is None:
            continue

        location = str(r.get("Location", "") or "")
        gig_county = get_gig_county(location, county_cache, default_for_prompt=requester_county)

        buffer_min = compute_buffer_minutes(requester_county, gig_county, ensemble)

        start_b = smin - buffer_min
        end_b   = emin + buffer_min
        blocked_by_date[d].append((start_b, end_b))

    return blocked_by_date


# ──────────────────────────────────────────────────────────────────────────────
# BUILD AVAILABILITY CALENDAR (HTML)
# ──────────────────────────────────────────────────────────────────────────────

def build_month_calendar(year: int,
                         month: int,
                         availability_by_date: dict[date, list[tuple[int, int]]]) -> str:
    """Build an HTML month calendar (Mon–Sat only) with availability ranges."""
    table_style = (
        "border-collapse:collapse; width:100%; max-width:900px; "
        "font-family:Arial,sans-serif; font-size:14px;"
    )
    th_style = (
        "border:1px solid #444; background:#e6f2ff; padding:6px; "
        "text-align:center; font-weight:bold;"
    )
    td_style = (
        "border:1px solid #888; padding:6px; width:16.6%; vertical-align:top;"
    )
    daynum_style = "font-weight:bold; font-size:16px; margin-bottom:4px;"

    cal = calendar.Calendar(firstweekday=0)  # Monday

    html = []
    month_name = calendar.month_name[month]

    html.append(f"<h2>Dates & Times We Can Perform — {month_name} {year}</h2>")
    html.append(f"<table style='{table_style}'>")

    # Header Mon–Sat
    header_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    html.append("<tr>")
    for dow in header_days:
        html.append(f"<th style='{th_style}'>{dow}</th>")
    html.append("</tr>")

    for week in cal.monthdayscalendar(year, month):
        mon_to_sat = week[:6]  # drop Sunday
        html.append("<tr>")

        for day in mon_to_sat:
            if day == 0:
                html.append(f"<td style='{td_style}'></td>")
                continue

            d = date(year, month, day)
            intervals = availability_by_date.get(d, [])

            if intervals:
                parts = [f"{format_minutes(s)}–{format_minutes(e)}" for s, e in intervals]
                content_html = "<br>".join(parts)
                daynum_html = f"<div style='{daynum_style}'>{day}</div>"
            else:
                content_html = ""
                daynum_html = f"<div style='{daynum_style} color:#bbbbbb;'>{day}</div>"

            html.append(
                f"<td style='{td_style}'>"
                f"{daynum_html}"
                f"<div>{content_html}</div>"
                f"</td>"
            )

        html.append("</tr>")

    html.append("</table><br>")
    return "".join(html)


# ──────────────────────────────────────────────────────────────────────────────
# GMAIL SENDER
# ──────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def get_gmail_creds():
    token = Path(TOKEN_PATH)
    creds_file = Path(CREDS_PATH)
    creds = None

    if token.exists():
        try:
            creds = UserCredentials.from_authorized_user_file(str(token), SCOPES)
        except Exception:
            token.unlink(missing_ok=True)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(GARequest())
            return creds
        except RefreshError:
            pass

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token.write_text(creds.to_json())
    return creds


def send_email(subject: str, html: str, to_addr: str):
    creds = get_gmail_creds()
    service = build("gmail", "v1", credentials=creds)

    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    raw = urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()


# ──────────────────────────────────────────────────────────────────────────────
# MAIN PROGRAM
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("Mixed Nuts Availability Calendar Emailer (v5)")
    print("-------------------------------------------")

    # Ensemble selection
    print("Which ensemble is this availability for?")
    print("  [M] Mixed Nuts (5-piece)  (default)")
    print("  [D] Mixed Nuts Duo: Sweet and Salty")
    ens_raw = input("Enter choice [M/d]: ").strip().lower()

    if ens_raw == "d":
        ensemble = "D"
        ensemble_label = "Mixed Nuts Duo"
        ensemble_display = "The Mixed Nuts Duo"
    else:
        ensemble = "M"
        ensemble_label = "Mixed Nuts"
        ensemble_display = "The Mixed Nuts"

    requester = input("\nFirst name of the person requesting availability: ").strip()
    if not requester:
        requester = "there"

    # Requesting venue county
    print("\nRequesting venue county.")
    print("Options: SL / Utah / Davis / Weber / Summit / Tooele / Wasatch / Washington / Other")
    county_raw = input("Enter county code [default SL]: ").strip()
    requester_county = parse_county_input(county_raw, default=COUNTY_SALT_LAKE)
    if not requester_county:
        requester_county = COUNTY_SALT_LAKE

    # Block Wednesdays?
    bw_raw = input("Block Wednesdays? [Y/n]: ").strip().lower()
    block_wednesdays = (bw_raw != "n")

    # Show duration in hours
    dur_raw = input("Duration of the requested show in hours? [1]: ").strip()
    gig_hours = 1
    if dur_raw:
        try:
            val = int(dur_raw)
            if val > 0:
                gig_hours = val
        except ValueError:
            gig_hours = 1
    min_required = gig_hours * 60

    today = date.today()
    default_start = today
    default_end   = today + timedelta(days=45)

    print()
    s = input(f"Start date [YYYY-MM-DD, default {default_start}]: ").strip()
    e = input(f"End date   [YYYY-MM-DD, default {default_end}]: ").strip()

    try:
        start = datetime.strptime(s, "%Y-%m-%d").date() if s else default_start
    except Exception:
        start = default_start

    try:
        end = datetime.strptime(e, "%Y-%m-%d").date() if e else default_end
    except Exception:
        end = default_end

    if end < start:
        start, end = end, start

    # Load county cache
    county_cache = load_county_cache()

    # Collect blocked intervals with county-based buffers
    blocked = collect_blocked(start, end, requester_county, block_wednesdays, county_cache, ensemble)

    # Save county cache (in case we prompted)
    save_county_cache(county_cache)

    # Build availability mapping, then filter windows that can't fit the requested gig length
    availability: dict[date, list[tuple[int, int]]] = {}
    for d in daterange(start, end):
        if is_blocked_date(d, block_wednesdays):
            continue
        intervals = blocked.get(d, [])
        avail_raw = complement_within_day(intervals)
        filtered = [(smin, emin) for (smin, emin) in avail_raw if (emin - smin) >= min_required]
        availability[d] = filtered

    # Build the monthly HTML calendars
    months = defaultdict(list)
    for d in availability:
        months[(d.year, d.month)].append(d)

    html_parts = []
    for (yr, mo), _ in sorted(months.items()):
        html_parts.append(build_month_calendar(yr, mo, availability))

    calendar_html = "".join(html_parts)

    # Subject with ensemble name and MM/DD/YYYY dates
    start_str = start.strftime("%m/%d/%Y")
    end_str   = end.strftime("%m/%d/%Y")
    subject = f"{ensemble_label} Availability: {start_str} to {end_str}"

    body = f"""
<p>Hi {escape(requester)},</p>

<p>Thanks for reaching out. We love bringing our upbeat Big Band music to your community.</p>

<p>Here is our availability. Pick a day and a start time for a full {gig_hours}-hour show within the times shown for that date.</p>

{calendar_html}

<p>If you let me know which date and time works best for your activity calendar,
I’ll get it scheduled on our end and send a confirmation right away.</p>

<p>Thanks again — we appreciate you thinking of us! Your residents are always
so wonderful to play for.</p>

<p><strong>— Keith Day</strong><br>
<strong>{escape(ensemble_display)}</strong><br>
<span style="font-style:italic; font-size:90%;">A Legacy Performers Production</span><br>
📞 <a href="tel:3853770451">385-377-0451</a> (call or text)<br>
📧 <a href="mailto:keith.day@legacyperformers.org">keith.day@legacyperformers.org</a><br>
🎶 <a href="https://facebook.com/TheMixedNutsSwingBand">facebook.com/TheMixedNutsSwingBand</a>
</p>
"""


    print("\nSending email to yourself for review...")
    send_email(subject, body, SEND_TO)
    print("✓ Email sent to:", SEND_TO)


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
