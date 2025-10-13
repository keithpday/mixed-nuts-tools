#!/usr/bin/env python3
# Mixed Nuts weekly gig mailer (Friday drafts with approval in Google Sheet)
# - Draft mode (default): writes/updates a single row in EmailDrafts for next week
# - --send-test: preview to Keith only (subject prefixed [TEST])
# - --send-approved: sends rows Approved?=TRUE and Sent? blank; else emails Keith a reminder
# - Body uses the full fancy HTML grid with styling from BandMembers

import re, argparse
from datetime import datetime, timedelta, date
import pandas as pd
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dateutil.tz import gettz
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from gspread.utils import rowcol_to_a1
from html import escape

# ---------- CONFIG ----------
CREDS_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
TOKEN_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.json"
SHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB = "CurrentYrSched"
MEMBERS_TAB  = "BandMembers"
DRAFTS_TAB   = "EmailDrafts"
TIMEZONE = "America/Denver"
KEITH_EMAIL = "keith.day@legacyperformers.org"

SIGNOFF_HTML = "<p>Best,</p><p>- Keith</p>"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

ALWAYS_INCLUDE = {"Bill Marsh", "Jay Christensen", "Katie Blunt"}

# ---------- SMALL HELPERS ----------
def normalize_signoff(body_html: str) -> str:
    """
    Remove any existing closing like 'Best,' and/or '-/–/— Keith' (entities or chars),
    whether wrapped in <p>...</p> or appearing around <br>, then add our standard two-line sign-off.
    """
    s = body_html

    # 1) Remove any 'Best,' paragraph(s)
    s = re.sub(r"\s*(?:<p>\s*Best,\s*</p>\s*)+", "", s, flags=re.IGNORECASE)

    # 2) Remove any single-line dash Keith paragraphs (entities or unicode, space or &nbsp;, optional)
    dash_group = r"(?:&mdash;|&ndash;|—|–|-)"
    nbsp_or_space = r"(?:&nbsp;|\s)?"

    # <p> - Keith </p>
    s = re.sub(rf"\s*(?:<p>\s*{dash_group}\s*{nbsp_or_space}Keith\s*</p>\s*)+", "", s, flags=re.IGNORECASE)

    # 3) Also remove raw '- Keith' lines that might be separated by <br> or newlines (defensive)
    s = re.sub(rf"(?:<br\s*/?>|\n|\r)?\s*{dash_group}\s*{nbsp_or_space}Keith\s*(?=(?:<br\s*/?>|\n|\r|$))", "", s, flags=re.IGNORECASE)

    # 4) Trim extra whitespace created by removals
    s = re.sub(r"(?:\s*<p>\s*</p>\s*)+", "", s, flags=re.IGNORECASE).strip()

    # 5) Append our standard sign-off
    return s + SIGNOFF_HTML

def _read_drafts_as_records(ws_d):
    """Return (records, header_map) from EmailDrafts. Preserves blank cells."""
    rows = ws_d.get_all_values()
    if not rows:
        return [], {}
    header = rows[0]
    records = []
    for r in rows[1:]:
        rec = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        records.append(rec)
    header_map = {h: i for i, h in enumerate(header)}
    return records, header_map

def _find_row_by_week(rows, header_map, week_str):
    """Find 1-based sheet row index (starting at 2 for first data row) and the record."""
    for i, rec in enumerate(rows, start=2):  # row 1 is the header
        if rec.get("Week", "") == week_str:
            return i, rec
    return None, None

def _get_field_variant(rec: dict, *variants: str) -> str:
    """Get a value from a record by any of several header names (case/space-insensitive)."""
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip()).casefold()
    norm_map = {norm(k): k for k in rec.keys()}
    for v in variants:
        k = norm_map.get(norm(v))
        if k is not None:
            return rec.get(k, "")
    return ""

def inject_comment_before_signoff(body_html: str, comment_text: str) -> str:
    """
    Insert comment (<p>...</p>) directly BEFORE the sign-off block.
    Recognizes:
      <p>Best,</p><p>- Keith</p>
      <p>- Keith</p>, <p>– Keith</p>, <p>— Keith</p>, and &ndash;/&mdash; variants.
    If no sign-off found, appends at the end.
    """
    comment_text = (comment_text or "").strip()
    if not comment_text:
        return body_html
    comment_html = f"<p>{escape(comment_text).replace('\\n', '<br>')}</p>"
    patterns = [
        r"(<p>\s*Best,\s*</p>\s*<p>\s*(?:&mdash;|&ndash;|—|–|-)\s*(&nbsp;)?\s*Keith\s*</p>)",
        r"(<p>\s*(?:&mdash;|&ndash;|—|–|-)\s*(&nbsp;)?\s*Keith\s*</p>)",
    ]
    for pat in patterns:
        m = re.search(pat, body_html, flags=re.IGNORECASE)
        if m:
            return body_html[:m.start()] + comment_html + body_html[m.start():]
    return body_html + comment_html

def _normalize(s: str) -> str:
    return (s or "").strip()

def _canon(s: str) -> str:
    return _normalize(s).casefold()

def _first_token(cell: str) -> str:
    """Pull the first plausible name token from a schedule cell."""
    s = _normalize(cell)
    if not s: return ""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return re.split(r"[,/&;]", s)[0].strip()

def _truthy(s: str) -> bool:
    return str(s).strip().lower() in {"1","true","yes","y","t"}

def _clean_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().strip('"').strip("'"))

def style_css_from_spec(spec: dict) -> str:
    if not spec: return ""
    css = []
    if spec.get("bg"): css.append(f"background:{spec['bg']};")
    if spec.get("fg"): css.append(f"color:{spec['fg']};")
    if spec.get("bold"): css.append("font-weight:bold;")
    if spec.get("italic"): css.append("font-style:italic;")
    if spec.get("underline"): css.append("text-decoration:underline;")
    return "".join(css)

FALLBACK_TOKEN_STYLE = {
    "yes": {"bg":"#ffffff","fg":"#f4557b","bold":False,"italic":False,"underline":True},
    "no":  {"bg":"#ffffff","fg":"#000000","bold":False,"italic":False,"underline":True},
    "sub": {"bg":"#ffffff","fg":"#f4557b","bold":True, "italic":False,"underline":True},
}

def load_band_members(values):
    """
    Build:
      - alias_to_full
      - full_to_email
      - key_to_style (by alias or full, casefolded)
      - token_style for 'yes','no','sub' (optional)
    """
    if not values:
        return {"alias_to_full": {}, "full_to_email": {}, "key_to_style": {}, "token_style": {}}

    header_idx = None
    header = []
    for i, row in enumerate(values[:10]):
        norm = [(c or "").strip().lower() for c in row]
        if "name" in norm and ("email" in norm or "email address" in norm):
            header_idx, header = i, row
            break
    if header_idx is None:
        return {"alias_to_full": {}, "full_to_email": {}, "key_to_style": {}, "token_style": {}}

    cols = { (h or "").strip().lower(): idx for idx, h in enumerate(header) }
    def col(*cands, default=None):
        for c in cands:
            if c in cols: return cols[c]
        return default

    c_name  = col("name")
    c_email = col("email", "email address")
    c_alias = col("alias")
    c_bg    = col("background")
    c_fg    = col("foreground")
    c_bold  = col("bold")
    c_ital  = col("italic")
    c_und   = col("underline")

    alias_to_full = {}
    full_to_email = {}
    key_to_style  = {}
    token_style   = {}

    for r in values[header_idx+1:]:
        if not any((x or "").strip() for x in r): continue

        name  = _normalize(r[c_name])  if c_name  is not None and c_name  < len(r) else ""
        email = _normalize(r[c_email]) if c_email is not None and c_email < len(r) else ""
        alias = _normalize(r[c_alias]) if c_alias is not None and c_alias < len(r) else ""
        if not name: continue

        bg = _normalize(r[c_bg]) if c_bg is not None and c_bg < len(r) else ""
        fg = _normalize(r[c_fg]) if c_fg is not None and c_fg < len(r) else ""
        bold = _truthy(r[c_bold]) if c_bold is not None and c_bold < len(r) else False
        ital = _truthy(r[c_ital]) if c_ital is not None and c_ital < len(r) else False
        und  = _truthy(r[c_und])  if c_und  is not None and c_und  < len(r) else False

        style = {"bg": bg, "fg": fg, "bold": bold, "italic": ital, "underline": und}

        if email: full_to_email[name] = email
        if alias: alias_to_full[alias] = name

        if name:  key_to_style[_canon(name)] = style
        if alias: key_to_style[_canon(alias)] = style

        ln = name.lower()
        if ln in {"yes","no","sub"}: token_style[ln] = style
        la = alias.lower()
        if la in {"yes","no","sub"}: token_style[la] = style

    return {
        "alias_to_full": alias_to_full,
        "full_to_email": full_to_email,
        "key_to_style": key_to_style,
        "token_style": token_style,
    }

def style_for(cell_text: str, key_to_style: dict, token_style: dict) -> str:
    raw = _normalize(cell_text)
    if not raw: return ""
    tok = _first_token(raw)
    if not tok: return ""
    low = tok.strip().lower()
    if low in {"yes","no","sub"}:
        spec = token_style.get(low) or FALLBACK_TOKEN_STYLE.get(low, {})
        return style_css_from_spec(spec)
    spec = key_to_style.get(_canon(tok), {})
    return style_css_from_spec(spec)

def resolve_full_name(cell_text: str, alias_to_full: dict, full_to_email: dict) -> str | None:
    tok = _first_token(cell_text)
    if not tok: return None
    low = tok.casefold()
    if low in {"yes", "no", "sub"}: return None
    if tok in alias_to_full: return alias_to_full[tok]
    if tok in full_to_email: return tok
    for full in full_to_email.keys():
        if full.casefold() == low:
            return full
    return None

def stack_time_cell(s: str) -> str:
    if not s: return ""
    s = str(s).strip()
    return re.sub(r"\s*[\-–]\s*", " –<br>", s, count=1)

def html_table(rows, style_lookup):
    if not rows:
        return "<p>No gigs scheduled for the selected week.</p>"

    def esc(x):
        return str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    header_bg = "#e6f2ff"
    TABLE_MIN_PX = 900
    COLW = {
        "date": "90px",
        "venue": "120px",
        "time": "100px",
        "location": "180px",
        "set": "60px",
        "pays": "70px",
        "role": "90px",
    }
    TD_BASE   = "padding:3px; vertical-align:middle; text-align:center; font-family:Arial,sans-serif; font-size:14px;"
    TD_WRAP20 = TD_BASE + "white-space:normal; word-break:break-word; overflow-wrap:anywhere;"
    TD_TIME   = TD_BASE
    TD_ROLE   = TD_BASE

    head = ("Date","Venue","Time","Location","Set","Pays","Vocal","Piano","Bass","Drums","Guitar","Vibes")

    s = [f"<div style='width:100%; overflow-x:auto;'>"]
    s.append(
        "<table border='1' cellpadding='3' cellspacing='0' "
        f"style='border-collapse:collapse; table-layout:fixed; min-width:{TABLE_MIN_PX}px; "
        "font-family:Arial,sans-serif; font-size:14px'>"
    )
    s.append(
        "<colgroup>"
        f"<col style='width:{COLW['date']}'>"
        f"<col style='width:{COLW['venue']}'>"
        f"<col style='width:{COLW['time']}'>"
        f"<col style='width:{COLW['location']}'>"
        f"<col style='width:{COLW['set']}'>"
        f"<col style='width:{COLW['pays']}'>"
        f"<col style='width:{COLW['role']}' span='6'>"
        "</colgroup>"
    )
    s.append(
        f"<tr style='font-weight:bold; background:{header_bg}'>"
        + "".join(f"<td style='{TD_BASE}'>{h}</td>" for h in head)
        + "</tr>"
    )

    for r in rows:
        time_disp  = stack_time_cell(r.get("time",""))
        time_html  = ("<div style='min-width:8ch; display:inline-block; text-align:center'>"
                      f"{time_disp}</div>")

        venue_html = ("<div style='min-width:12ch; max-width:20ch; display:inline-block; text-align:center; "
                      "white-space:normal; word-break:break-word; overflow-wrap:anywhere'>"
                      f"{esc(r.get('venue',''))}</div>")

        location_html = ("<div style='min-width:12ch; max-width:20ch; display:inline-block; text-align:center; "
                         "white-space:normal; word-break:break-word; overflow-wrap:anywhere'>"
                         f"{esc(r.get('location',''))}</div>")

        def role_td(val):
            return f"<td style='{TD_ROLE}{style_lookup(val)}'>{esc(val)}</td>"

        s.append(
            "<tr>"
            f"<td style='{TD_BASE}'>{esc(r['date_disp'])}</td>"
            f"<td style='{TD_WRAP20}'>{venue_html}</td>"
            f"<td style='{TD_TIME}'>{time_html}</td>"
            f"<td style='{TD_WRAP20}'>{location_html}</td>"
            f"<td style='{TD_BASE}'>{esc(r.get('set',''))}</td>"
            f"<td style='{TD_BASE}'>{esc(r.get('pays',''))}</td>"
            + role_td(r.get("vocal",""))
            + role_td(r.get("piano",""))
            + role_td(r.get("bass",""))
            + role_td(r.get("drums",""))
            + role_td(r.get("guitar",""))
            + role_td(r.get("vibes",""))
            + "</tr>"
        )

    s.append("</table>")
    s.append("</div>")
    return "\n".join(s)

# ---------- AUTH ----------
def get_credentials():
    """
    Loads OAuth token and refreshes it silently (no browser).
    Falls back to interactive auth ONLY when running interactively.
    In cron/headless, exits with an explicit message instead of launching a browser.
    """
    import os, sys
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request as GARequest
    from google.auth.exceptions import RefreshError

    token_path = Path(TOKEN_PATH)
    creds_path = Path(CREDS_PATH)

    # 1) Try to load existing token
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            try: token_path.unlink()
            except FileNotFoundError: pass
            creds = None

    # 2) Check scope coverage even if creds not valid yet
    scope_missing = True
    if creds:
        token_scopes = set(getattr(creds, "scopes", []) or [])
        scope_missing = not set(SCOPES).issubset(token_scopes)

    # 3) If we have a token with the right scopes, try silent refresh
    if creds and not scope_missing:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GARequest())
            except RefreshError:
                # refresh failed → will require interactive reauth
                creds = None
        # If still valid (either refreshed or not expired), return
        if creds and creds.valid:
            return creds

    # 4) At this point, we need interactive auth (no valid/refreshable token, or scopes changed)
    #    Only attempt a browser if we are interactive; otherwise bail with a clear message.
    is_interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not is_interactive:
        raise SystemExit(
            "OAuth re-authorization is required but no interactive browser is available.\n"
            "Fix: run this once interactively from a terminal on the same machine:\n"
            "  python3 /home/keith/PythonProjects/projects/Mixed_Nuts/weekly_gig_mailer_drafts.py --send-test\n"
            "After that, cron will run unattended (the token will refresh silently)."
        )

    # 5) Interactive: perform the browser flow and save the token
    if not creds_path.exists():
        raise SystemExit(f"Missing OAuth client file: {creds_path}")

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    # Use local server (opens browser) when interactive
    creds = flow.run_local_server(port=0)   # first-run: will obtain a refresh token
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def open_ws(creds, sheet_key, tab):
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_key)
    return sh.worksheet(tab)

# ---------- DATE HELPERS ----------
def week_range(date_in: date):
    days_since_sun = (date_in.weekday() + 1) % 7
    sunday = date_in - timedelta(days=days_since_sun)
    saturday = sunday + timedelta(days=6)
    return sunday, saturday

def next_week_range(today: date):
    this_sun, _ = week_range(today)
    next_sun = this_sun + timedelta(days=7)
    return next_sun, next_sun + timedelta(days=6)

# ---------- EMAIL BUILD ----------
def build_message(subject, html, to_list):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = ", ".join(sorted(to_list))
    msg.attach(MIMEText(html, "html"))
    return {"raw": urlsafe_b64encode(msg.as_bytes()).decode("utf-8")}

def send_gmail(creds, body):
    svc = build("gmail", "v1", credentials=creds)
    return svc.users().messages().send(userId="me", body=body).execute()

# ---------- MAIN DRAFT ----------
def draft_email(creds, start: date, end: date):
    ws = open_ws(creds, SHEET_ID, SCHEDULE_TAB)
    values = ws.get_all_values()
    if not values:
        raise SystemExit("Schedule tab is empty.")
    headers, rows = values[0], values[1:]

    clean_headers = [_clean_header(h) for h in headers]
    def idx(pattern: str, required: bool = True):
        rx = re.compile(pattern, re.I)
        for i, h in enumerate(clean_headers):
            if rx.fullmatch(h):
                return i
        if required:
            raise SystemExit(f"Could not find column matching /{pattern}/. Found headers: {clean_headers}")
        return None

    idx_date  = idx(r"date")
    idx_venue = idx(r"venue")
    idx_time  = idx(r"time")
    idx_loc   = idx(r"location")

    idx_set   = idx(r"set", required=False)
    idx_pays  = idx(r"pays?", required=False)

    idx_vocal  = idx(r"vocal(s)?")
    idx_piano  = idx(r"(piano|keys?|keyboard)")
    idx_bass   = idx(r"bass")
    idx_drums  = idx(r"drum(s)?")
    idx_guitar = idx(r"guitar")
    idx_vibes  = idx(r"(vibes?|vibraphone)")

    def get_val(row, i):
        return row[i] if i is not None and i < len(row) else ""

    week_rows = []
    for r in rows:
        d_ts = pd.to_datetime(get_val(r, idx_date), errors="coerce")
        if pd.isna(d_ts):
            continue
        d = d_ts.date()
        if not (start <= d <= end):
            continue

        week_rows.append({
            "date_disp": d.strftime("%a, %b %-d"),
            "venue":     get_val(r, idx_venue),
            "time":      get_val(r, idx_time),
            "location":  get_val(r, idx_loc),
            "set":       get_val(r, idx_set),
            "pays":      get_val(r, idx_pays),
            "vocal":     get_val(r, idx_vocal),
            "piano":     get_val(r, idx_piano),
            "bass":      get_val(r, idx_bass),
            "drums":     get_val(r, idx_drums),
            "guitar":    get_val(r, idx_guitar),
            "vibes":     get_val(r, idx_vibes),
        })

    ws_m = open_ws(creds, SHEET_ID, MEMBERS_TAB)
    members_blob = load_band_members(ws_m.get_all_values())

    date_range = f"{start.strftime('%a, %b %-d')}–{end.strftime('%a, %b %-d, %Y')}"
    subject = f"Mixed Nuts week of {date_range}"
    body_html = (
        "<p>Hello Mixed Nuts,</p>"
        f"<p>Here is the schedule for the week of {date_range}:</p>"
        f"{html_table(week_rows, lambda v: style_for(v, members_blob['key_to_style'], members_blob['token_style']))}"
        f"{SIGNOFF_HTML}"
    )

    # Recipients: scheduled players + ALWAYS_INCLUDE
    alias_to_full = members_blob["alias_to_full"]
    full_to_email = members_blob["full_to_email"]

    scheduled_full_names = set()
    for r in week_rows:
        for role in ("vocal", "piano", "bass", "drums", "guitar", "vibes"):
            full = resolve_full_name(r.get(role, ""), alias_to_full, full_to_email)
            if full:
                scheduled_full_names.add(full)

    for nm in ALWAYS_INCLUDE:
        full = resolve_full_name(nm, alias_to_full, full_to_email) or nm
        if full:
            scheduled_full_names.add(full)

    recipients = sorted(
        { full_to_email.get(full) for full in scheduled_full_names if full_to_email.get(full) },
        key=lambda s: s.lower()
    )

    # Write/overwrite in EmailDrafts (header-aware)
    ws_d = open_ws(creds, SHEET_ID, DRAFTS_TAB)
    all_rows = ws_d.get_all_values()
    if not all_rows:
        raise SystemExit("EmailDrafts tab is empty or missing a header row.")

    header = all_rows[0]
    def _hnorm(h): return re.sub(r"\s+", " ", (h or "").strip()).casefold()
    hmap = {_hnorm(h): i for i, h in enumerate(header)}

    def col(name, required=True):
        i = hmap.get(_hnorm(name))
        if i is None and required:
            raise SystemExit(f"EmailDrafts is missing a '{name}' column. Found: {header}")
        return i

    c_week    = col("Week")
    c_subject = col("Subject")
    c_body    = col("Body")
    c_recip   = col("Recipients")
    c_sent    = col("Sent?", required=False) or col("Sent", required=False) or col("Sent Date", required=False)
    c_comment = col("Comment", required=False)  # optional
    # c_approved may or may not exist; we don't need its index here

    week_str = start.strftime("%Y-%m-%d")

    row_idx = None
    for i, r in enumerate(all_rows[1:], start=2):
        if c_week < len(r) and r[c_week] == week_str:
            row_idx = i
            break

    if row_idx:
        existing = all_rows[row_idx - 1]
        row_out = list(existing) + [""] * max(0, len(header) - len(existing))
    else:
        row_out = [""] * len(header)

    row_out[c_week]    = week_str
    row_out[c_subject] = subject
    row_out[c_body]    = body_html
    row_out[c_recip]   = ";".join(recipients)

    if row_idx:
        first_a1 = rowcol_to_a1(row_idx, 1)
        last_a1  = rowcol_to_a1(row_idx, len(header))
        ws_d.update(values=[row_out], range_name=f"{first_a1}:{last_a1}")
        print(f"✅ Updated draft for week {week_str} in EmailDrafts.")
    else:
        ws_d.append_row(row_out)
        print(f"✅ Added draft for week {week_str} in EmailDrafts.")

# ---------- SEND (with reminder) ----------
def send_approved(creds):
    ws_d = open_ws(creds, SHEET_ID, DRAFTS_TAB)
    rows, header_map = _read_drafts_as_records(ws_d)
    if not rows:
        print("No drafts found.")
        return

    # Header-aware location for Sent?
    header = ws_d.row_values(1)
    def _hnorm(h): return re.sub(r"\s+", " ", (h or "").strip()).casefold()
    hmap = {_hnorm(h): i for i, h in enumerate(header)}
    def col(name, required=True):
        i = hmap.get(_hnorm(name))
        if i is None and required:
            raise SystemExit(f"EmailDrafts is missing a '{name}' column. Found: {header}")
        return i
    c_sent = col("Sent?", required=False) or col("Sent", required=False) or col("Sent Date", required=False)

    sent_any = False
    for i, rec in enumerate(rows, start=2):  # sheet row (header is 1)
        approved = _truthy(_get_field_variant(rec, "Approved?", "Approved", "Approval"))
        sent_mark = (_get_field_variant(rec, "Sent?", "Sent", "Sent Date") or "").strip()
        if approved and not sent_mark:
            subject   = _get_field_variant(rec, "Subject")
            body      = _get_field_variant(rec, "Body")
            comment   = _get_field_variant(rec, "Comment", "Comments", "Note", "Notes")
            body = normalize_signoff(body)
            body = inject_comment_before_signoff(body, comment)
            recipients_str = _get_field_variant(rec, "Recipients", "To", "Emails")
            # accept ; , or whitespace as separators
            parts = re.split(r"[;,\s]+", recipients_str or "")
            recipients = [x.strip() for x in parts if x.strip()]
            week_lbl = _get_field_variant(rec, "Week")
            print(f"[send] row={i} week={week_lbl} approved={approved} sent_mark='{sent_mark}' rcpts={len(recipients)}")

            if not recipients:
                if c_sent is not None:
                    ws_d.update_cell(i, c_sent + 1, f"SKIPPED {datetime.now().strftime('%Y-%m-%d %H:%M')} (no recipients)")
                else:
                    print(f"Skipped row {i}: no recipients")
                continue

            msg = build_message(subject or "(no subject)", body, recipients)
            send_gmail(creds, msg)
            ts = datetime.now(gettz(TIMEZONE)).strftime("%Y-%m-%d %H:%M")
            if c_sent is not None:
                ws_d.update_cell(i, c_sent + 1, ts)
            print(f"📧 Sent approved email for week {_get_field_variant(rec, 'Week') or '?'}")
            sent_any = True

    if not sent_any:
        # Reminder to Keith
        svc = build("gmail", "v1", credentials=creds)
        sheet_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"
        subj = "Reminder: No approved Mixed Nuts weekly email yet"
        html = (
            "<p>Hi Keith,</p>"
            "<p>No rows were marked <b>Approved?=TRUE</b> in <i>EmailDrafts</i>, so nothing was sent.</p>"
            f"<p>Please review/approve here:<br><a href='{sheet_url}'>{sheet_url}</a></p>"
            "<p>— Friday Mailer</p>"
        )
        body = build_message(subj, html, [KEITH_EMAIL])
        svc.users().messages().send(userId="me", body=body).execute()
        print("🔔 Reminder sent to Keith.")

# ---------- SEND TEST EMAIL ----------
def send_test(creds, week_start: date | None):
    """Send the draft to Keith only, inserting Comment if present."""
    ws_d = open_ws(creds, SHEET_ID, DRAFTS_TAB)
    rows, header_map = _read_drafts_as_records(ws_d)
    if not rows:
        print("No drafts found.")
        return

    if week_start is None:
        today = datetime.now(gettz(TIMEZONE)).date()
        week_start, _ = next_week_range(today)

    week_str = week_start.strftime("%Y-%m-%d")
    rownum, rec = _find_row_by_week(rows, header_map, week_str)
    if not rec:
        print(f"No draft row found for Week {week_str}. Run draft first.")
        return

    subject = _get_field_variant(rec, "Subject")
    body    = _get_field_variant(rec, "Body")
    comment = _get_field_variant(rec, "Comment", "Comments", "Note", "Notes")
    body = normalize_signoff(body)
    body = inject_comment_before_signoff(body, comment)
    subject = f"[TEST] {subject}" if subject else "[TEST] (no subject)"

    msg = build_message(subject, body, [KEITH_EMAIL])
    send_gmail(creds, msg)
    print(f"📧 Sent TEST email for week {week_str} to {KEITH_EMAIL}")

# ---------- CLI ----------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--send-approved", action="store_true",
                        help="Send approved drafts instead of creating a new one.")
    parser.add_argument("--send-test", action="store_true",
                        help="Send a preview of the draft to Keith only (subject prefixed [TEST]).")
    parser.add_argument("--week-of", type=str, default=None,
                        help="YYYY-MM-DD (any date in the target week). Default: prompt (defaults to next Sunday).")
    args = parser.parse_args()

    creds = get_credentials()
    today = datetime.now(gettz(TIMEZONE)).date()

    # Determine default next Sunday
    next_sunday, _ = next_week_range(today)

    # Always prompt unless --week-of is explicitly provided
    if args.week_of:
        base = pd.to_datetime(args.week_of).date()
        week_start, _ = week_range(base)
    else:
        print()
        print("Mixed Nuts Weekly Gig Mailer")
        print("-----------------------------")
        print(f"Default week begins on Sunday: {next_sunday.strftime('%Y-%m-%d')}")
        user_input = input("Enter week beginning date (YYYY-MM-DD) or press Enter for default: ").strip()
        if user_input:
            try:
                base = pd.to_datetime(user_input).date()
                week_start, _ = week_range(base)
            except Exception:
                print("Invalid date format. Using default next Sunday.")
                week_start = next_sunday
        else:
            week_start = next_sunday

    # Show chosen week
    print(f"\nSelected week beginning: {week_start.strftime('%Y-%m-%d')}\n")

    # Branch to the requested action
    if args.send_test:
        confirm = input("Send TEST email to Keith only? (y/n): ").strip().lower()
        if confirm == "y":
            send_test(creds, week_start)
        else:
            print("Cancelled.")
        return

    if args.send_approved:
        confirm = input("Send FINAL approved weekly email to all recipients? (y/n): ").strip().lower()
        if confirm == "y":
            send_approved(creds)
        else:
            print("Cancelled.")
        return

    # Default action: create/update draft for selected week
    start, end = week_range(week_start)
    draft_email(creds, start, end)

if __name__ == "__main__":
    main()

