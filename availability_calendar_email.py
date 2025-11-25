#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
availability_calendar_email.py
───────────────────────────────────────────────────────────────────────────────
Generates an HTML month-view availability calendar based on Google Sheets
schedule, then emails it to:

    keith.day@legacyperformers.org

You can then forward or edit the email before sending to venues.

Uses:
- CurrentYrSched tab
- Columns: Date, Venue, Location, Time, Set
- Time format: "1:30 pm - 3:00 pm"
- Skips Sundays, Jan 1, Dec 25
- Applies travel buffer:
    Inside SL County? → 2 hrs
    Outside SL County? → 3 hrs

Produces:
- Calendar(s) in HTML form (one per month in date range)
- Email delivered using Gmail API
"""

import re
import calendar
from datetime import date, datetime, timedelta
from collections import defaultdict
from html import escape

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from base64 import urlsafe_b64encode
from pathlib import Path
from google.auth.transport.requests import Request as GARequest
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
SHEET_ID        = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB    = "CurrentYrSched"

CREDS_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
TOKEN_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.json"

SEND_TO = "keith.day@legacyperformers.org"

SIGNATURE = """
<p>Best,</p>
<p>- Keith</p>
"""

DAY_START_MIN = 9 * 60
DAY_END_MIN   = 21 * 60
HOLIDAYS_MMDD = {(1,1), (12,25)}

GROUP_DEFAULT = "Mixed Nuts"
GROUP_DUO     = "Mixed Nuts Duo: Sweet and Salty"
GROUP_TRIO    = "Mixed Nuts: Trio Blend"
GROUP_QUAD    = "Mixed Nuts: Quad Blend"

# ──────────────────────────────────────────────────────────────────────────────
# BASIC HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def is_blocked_date(d: date) -> bool:
    return d.weekday() == 6 or (d.month, d.day) in HOLIDAYS_MMDD

def daterange(start, end):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)

def _to_minutes(h, m, ap):
    ap = ap.lower()
    if ap.startswith("a"):
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return h*60 + m

_TIME_RANGE_RE = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*[-–]\s*(\d{1,2}):(\d{2})\s*([aApP][mM]?)\s*$"
)

def parse_time_range(text):
    if not text:
        return (None, None)
    t = text.replace("—","-").replace("–","-")
    m = _TIME_RANGE_RE.match(t)
    if not m:
        return (None, None)
    sh, sm, sap, eh, em, eap = m.groups()
    return _to_minutes(int(sh),int(sm),sap), _to_minutes(int(eh),int(em),eap)

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


def determine_group(set_text):
    s = (set_text or "").lower()
    if "duo" in s: return GROUP_DUO
    if "trio" in s: return GROUP_TRIO
    if "quad" in s: return GROUP_QUAD
    return GROUP_DEFAULT

def complement_within_day(blocked):
    day_start, day_end = DAY_START_MIN, DAY_END_MIN
    clipped = []
    for s, e in blocked:
        s = max(s, day_start)
        e = min(e, day_end)
        if e > s:
            clipped.append((s,e))
    clipped.sort()
    merged = []
    for s,e in clipped:
        if not merged or s > merged[-1][1]:
            merged.append((s,e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
    avail = []
    cur = day_start
    for s,e in merged:
        if s > cur:
            avail.append((cur,s))
        cur = max(cur, e)
    if cur < day_end:
        avail.append((cur, day_end))
    if not merged and not avail:
        avail = [(day_start, day_end)]
    return avail

def format_minutes(m):
    h24 = m//60
    mins = m%60
    ap = "am" if h24 < 12 else "pm"
    h12 = h24%12
    if h12 == 0: h12 = 12
    return f"{h12}:{mins:02d} {ap}"

# ──────────────────────────────────────────────────────────────────────────────
# COLLECT BLOCKED INTERVALS FROM GOOGLE SHEET
# ──────────────────────────────────────────────────────────────────────────────

def collect_blocked(creds, start_date, end_date, buffer_min):
    gc = gspread.authorize(
        Credentials.from_service_account_file(
            SERVICE_ACCOUNT,
            scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
    )
    ws = gc.open_by_key(SHEET_ID).worksheet(SCHEDULE_TAB)
    rows = ws.get_all_records()

    blocked_by_date = defaultdict(list)

    for r in rows:
        d = parse_sheet_date(r.get("Date"))
        if not d or d < start_date or d > end_date:
            continue
        if is_blocked_date(d):
            continue

        t = r.get("Time","")
        smin, emin = parse_time_range(str(t))
        if smin is None:
            continue

        start_b = smin - buffer_min
        end_b   = emin + buffer_min
        blocked_by_date[d].append((start_b, end_b))

    return blocked_by_date

# ──────────────────────────────────────────────────────────────────────────────
# BUILD AVAILABILITY CALENDAR (HTML)
# ──────────────────────────────────────────────────────────────────────────────

def build_month_calendar(year, month, availability_by_date):
    # Wider layout, Mon–Sat only, email-safe formatting
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
    daynum_style = (
        "font-weight:bold; font-size:16px; margin-bottom:4px;"
    )

    # Monday-first calendar (0 = Monday)
    cal = calendar.Calendar(firstweekday=0)

    html = []
    month_name = calendar.month_name[month]

    # Month header
    html.append(f"<h2>{month_name} {year}</h2>")
    html.append(f"<table style='{table_style}'>")

    # Header row: Mon–Sat
    header_days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    html.append("<tr>")
    for dow in header_days:
        html.append(f"<th style='{th_style}'>{dow}</th>")
    html.append("</tr>")

    # Each week
    for week in cal.monthdayscalendar(year, month):
        # week = [Mon, Tue, Wed, Thu, Fri, Sat, Sun]
        mon_to_sat = week[:6]  # Skip Sunday entirely

        html.append("<tr>")
        for day in mon_to_sat:
            if day == 0:
                # Empty cell (spacer)
                html.append(f"<td style='{td_style}'></td>")
                continue

            d = date(year, month, day)
            intervals = availability_by_date.get(d, [])

            # Build content for availability
            if intervals:
                parts = [
                    f"{format_minutes(s)}–{format_minutes(e)}"
                    for s, e in intervals
                ]
                content_html = "<br>".join(parts)

                # Black day number = availability exists
                daynum_html = (
                    f"<div style='{daynum_style}'>{day}</div>"
                )
            else:
                content_html = ""

                # Gray day number = no availability
                daynum_html = (
                    f"<div style='{daynum_style} color:#bbbbbb;'>{day}</div>"
                )

            # Render final cell
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
            creds = Credentials.from_authorized_user_file(str(token), SCOPES)
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

def send_email(subject, html, to_addr):
    creds = get_gmail_creds()
    service = build("gmail", "v1", credentials=creds)

    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    raw = urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()

# ──────────────────────────────────────────────────────────────────────────────
# MAIN PROGRAM
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("Mixed Nuts Availability Calendar Emailer")
    print("---------------------------------------")

    today = date.today()
    default_start = today
    default_end   = today + timedelta(days=45)

    s = input(f"Start date [YYYY-MM-DD, default {default_start}]: ").strip()
    e = input(f"End date   [YYYY-MM-DD, default {default_end}]: ").strip()

    try:
        start = datetime.strptime(s,"%Y-%m-%d").date() if s else default_start
    except: start = default_start

    try:
        end = datetime.strptime(e,"%Y-%m-%d").date() if e else default_end
    except: end = default_end

    inside = input("Inside Salt Lake County? [Y/n]: ").strip().lower()
    buffer_min = 120 if inside != "n" else 180

    # Gather blocked intervals
    blocked = collect_blocked(None, start, end, buffer_min)

    # Build availability map
    availability = {}
    for d in daterange(start, end):
        if is_blocked_date(d):
            continue
        intervals = blocked.get(d, [])
        availability[d] = complement_within_day(intervals)

    # Build monthly HTML calendars
    months = defaultdict(list)
    for d in availability:
        months[(d.year, d.month)].append(d)

    html_parts = []
    for (yr,mo), _ in sorted(months.items()):
        html_parts.append(build_month_calendar(yr,mo,availability))

    calendar_html = "".join(html_parts)

    # Build email
    subject = f"Mixed Nuts Availability: {start} to {end}"
    body = (
        "<p>Hello Keith,</p>"
        "<p>Here is the availability calendar you requested.</p>"
        f"{calendar_html}"
        f"{SIGNATURE}"
    )

    print("\nSending email...")
    send_email(subject, body, SEND_TO)
    print("✓ Email sent to:", SEND_TO)

if __name__ == "__main__":
    main()
