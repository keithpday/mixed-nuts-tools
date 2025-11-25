#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
availability_calendar_email_v3.py
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
- Travel buffer based on county of requesting venue vs. gig location:
    * If requester county == gig county → 3 hours
    * If requester county != gig county and (either is Salt Lake) → 4 hours
    * If requester county != gig county and neither is Salt Lake → 5 hours
- Counties inferred from Location via keyword mapping; if unknown, prompted once
  and cached in a JSON file.
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

DAY_START_MIN = 9 * 60
DAY_END_MIN   = 21 * 60
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

# City/area keyword mapping to county (very simple substring match, lowercased)
CITY_TO_COUNTY = {
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

    "bountiful": "Davis",
    "woods cross": "Davis",
    "centerville": "Davis",
    "farmington": "Davis",
    "kaysville": "Davis",
    "layton": "Davis",
    "clearfield": "Davis",
    "syracuse": "Davis",

    "ogden": "Weber",
    "north ogden": "Weber",
    "south ogden": "Weber",
    "roy": "Weber",
    "pleasant view": "Weber",

    "park city": "Summit",
    "kamas": "Summit",
    "coalville": "Summit",

    "tooele": "Tooele",
    "stansbury": "Tooele",   # Stansbury Park
    "grantsville": "Tooele",
    "erda": "Tooele",

    "heber": "Wasatch",
    "midway": "Wasatch",
    "charleston": "Wasatch",

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
    """True if date is Sunday, holiday, or (optionally) Wednesday."""
    if d.weekday() == 6:  # Sunday
        return True
    if block_wednesdays and d.weekday() == 2:  # Wednesday
        return True
    if (d.month, d.day) in HOLIDAYS_MMDD:
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


def compute_buffer_minutes(requester_county: str, gig_county: str) -> int:
    """Compute travel buffer in minutes based on requester vs. gig county."""
    r = requester_county
    g = gig_county

    if not r or not g:
        # Conservative default
        return 4 * 60

    if r == g:
        return 3 * 60

    # If either is Salt Lake, but they differ
    if r == COUNTY_SALT_LAKE or g == COUNTY_SALT_LAKE:
        return 4 * 60

    # Different non-SL counties
    return 5 * 60


# ──────────────────────────────────────────────────────────────────────────────
# COLLECT BLOCKED INTERVALS FROM GOOGLE SHEET
# ──────────────────────────────────────────────────────────────────────────────

def collect_blocked(start_date: date,
                    end_date: date,
                    requester_county: str,
                    block_wednesdays: bool,
                    county_cache: dict) -> dict[date, list[tuple[int, int]]]:
    """Build blocked intervals per date using per-gig travel buffers."""
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

        t = r.get("Time", "")
        smin, emin = parse_time_range(str(t))
        if smin is None or emin is None:
            continue

        location = str(r.get("Location", "") or "")
        gig_county = get_gig_county(location, county_cache, default_for_prompt=requester_county)

        buffer_min = compute_buffer_minutes(requester_county, gig_county)

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

    html.append(f"<h2>{month_name} {year}</h2>")
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
    print("Mixed Nuts Availability Calendar Emailer (v3)")
    print("-------------------------------------------")

    requester = input("First name of the person requesting availability: ").strip()
    if not requester:
        requester = "there"

    # Requester county prompt
    print("\nRequesting venue county.")
    print("Options: SL / Utah / Davis / Weber / Summit / Tooele / Wasatch / Washington / Other")
    county_raw = input("Enter county code [default SL]: ").strip()
    requester_county = parse_county_input(county_raw, default=COUNTY_SALT_LAKE)
    if not requester_county:
        requester_county = COUNTY_SALT_LAKE

    # Block Wednesdays?
    bw_raw = input("Block Wednesdays? [Y/n]: ").strip().lower()
    block_wednesdays = (bw_raw != "n")

    today = date.today()
    default_start = today
    default_end   = today + timedelta(days=45)

    s = input(f"\nStart date [YYYY-MM-DD, default {default_start}]: ").strip()
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

    # Load cache of known locations → counties
    county_cache = load_county_cache()

    # Collect blocked intervals with county-based buffers
    blocked = collect_blocked(start, end, requester_county, block_wednesdays, county_cache)

    # Save cache back to disk (in case we prompted)
    save_county_cache(county_cache)

    # Build availability mapping
    availability: dict[date, list[tuple[int, int]]] = {}
    for d in daterange(start, end):
        if is_blocked_date(d, block_wednesdays):
            continue
        intervals = blocked.get(d, [])
        availability[d] = complement_within_day(intervals)

    # Build month calendars
    months = defaultdict(list)
    for d in availability:
        months[(d.year, d.month)].append(d)

    html_parts = []
    for (yr, mo), _ in sorted(months.items()):
        html_parts.append(build_month_calendar(yr, mo, availability))

    calendar_html = "".join(html_parts)

    subject = f"Mixed Nuts Availability: {start} to {end}"

    body = f"""
<p>Hello {escape(requester)},</p>

<p>Thank you for reaching out to check our availability. We always look forward to
visiting your community and sharing an upbeat, feel-good hour of music from the
1950s and 1960s with your residents.</p>

<p>Below is our availability for the date range you requested.
Each time range shown represents a block where our band is fully available to come
perform a one-hour show at your community. These windows already include our
standard travel and equipment setup buffers, based on where our other shows are
scheduled, so any time you choose within a listed window works fine.</p>

{calendar_html}

<p>If you let me know which date and time works best for your activity calendar,
I’ll get it scheduled on our end and send a confirmation right away.</p>

<p>Thanks again — we appreciate you thinking of us! Your residents are always
so wonderful to play for.</p>

<p><strong>— Keith Day</strong><br>
<strong>The Mixed Nuts</strong><br>
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
