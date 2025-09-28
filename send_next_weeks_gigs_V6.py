#!/usr/bin/env python3
# Mixed Nuts weekly gig mailer (Sun–Sat), with interactive beginning-Sunday prompt.
# - Loads aliases, emails, and styling from the BandMembers tab (no hard-coded tables).
# - Prints planned recipients line-by-line with alias — full — email, and flags issues.
# - Lists unmatched schedule tokens to catch misspellings.

import os, re, argparse
from pathlib import Path
from datetime import datetime, timedelta, date
import pandas as pd
from dateutil.tz import gettz

import gspread
import time, random
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from base64 import urlsafe_b64encode
from html import escape

# ---------------- CONFIG ----------------
# Accepts either the raw ID or a full URL; we normalize it below.
SHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB = "CurrentYrSched"
MEMBERS_TAB  = "BandMembers"
TIMEZONE = "America/Denver"

ALWAYS_INCLUDE = {"Bill Marsh", "Jay Christensen", "Katie Blunt"}
TEST_RECIPIENT = "keith.day@legacyperformers.org"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# ---------------- RETRY HELPERS ----------------
RETRY_STATUS = {429, 500, 502, 503, 504}

def _status_from_apierror(e) -> int | None:
    # gspread wraps a requests.Response; try to read status, else parse from string "[503]"
    resp = getattr(e, "response", None)
    if resp and hasattr(resp, "status_code"):
        return resp.status_code
    m = re.search(r"\[(\d{3})\]", str(e))
    return int(m.group(1)) if m else None

def with_retries(func, *args, **kwargs):
    """Retry gspread calls on 429/5xx with exponential backoff + jitter."""
    backoff = 1.0
    attempts = 6
    for attempt in range(1, attempts + 1):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            code = _status_from_apierror(e)
            if code in RETRY_STATUS and attempt < attempts:
                sleep = backoff + random.uniform(0, 0.5)
                print(f"⚠️ Google Sheets {code}. Retrying in {sleep:.1f}s (attempt {attempt}/{attempts-1})…")
                time.sleep(sleep)
                backoff *= 2
                continue
            raise

# ---------------- ID / AUTH HELPERS ----------------
def normalize_sheet_id(value: str) -> str:
    value = (value or "").strip()
    m = re.search(r"/d/([A-Za-z0-9-_]+)", value)
    if m:
        return m.group(1)
    # strip any accidental suffix
    return value.split("?")[0].split("/edit")[0].strip()

def get_credentials(creds_path=None, token_path=None):
    # Your preferred defaults
    default_creds = Path("/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
    default_token = Path("/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.json")

    # Use overrides if provided, else defaults
    creds_path = Path(creds_path).expanduser() if creds_path else default_creds
    token_path = Path(token_path).expanduser() if token_path else default_token

    # Helpful trace
    print(f"Using creds: {creds_path}")
    print(f"Using token: {token_path}")

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES) if token_path.exists() else None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            try:
                creds.refresh(Request())
            except RefreshError:
                # Wipe bad token and re-auth
                try: token_path.unlink()
                except FileNotFoundError: pass
                if not creds_path.exists():
                    raise SystemExit(f"Missing OAuth client: {creds_path}")
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            if not creds_path.exists():
                raise SystemExit(f"Missing OAuth client: {creds_path}")
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)

        # Ensure folder exists, then save
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return creds

def open_ws(creds, sheet_key, tab):
    gc = gspread.authorize(creds)
    sh = with_retries(gc.open_by_key, sheet_key)
    return with_retries(sh.worksheet, tab)

# ---------------- DATE / FORMAT HELPERS ----------------
def parse_date(val):
    if not val or str(val).strip() == "":
        return None
    try:
        return pd.to_datetime(val).to_pydatetime().date()
    except Exception:
        return None

def week_range_sun_sat(containing_date: date):
    days_since_sun = (containing_date.weekday() + 1) % 7  # Mon=0..Sun=6
    sunday = containing_date - timedelta(days=days_since_sun)
    saturday = sunday + timedelta(days=6)
    return sunday, saturday

def next_week_sun_sat(today: date):
    this_sun, _ = week_range_sun_sat(today)
    next_sun = this_sun + timedelta(days=7)
    return next_sun, next_sun + timedelta(days=6)

def stack_time_cell(s: str) -> str:
    """Insert a line break after the first dash/en-dash."""
    if not s:
        return ""
    s = str(s).strip()
    return re.sub(r"\s*[\-–]\s*", " –<br>", s, count=1)

# ---------------- MEMBERS / STYLING LOADER ----------------
def _truthy(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y", "t"}

def _normalize(s: str) -> str:
    return (s or "").strip()

def _canon(s: str) -> str:
    return _normalize(s).casefold()

def _first_token(cell: str) -> str:
    """
    Pull the first plausible name token from a schedule cell.
    Splits on commas, slashes, ampersands, parentheses.
    """
    s = _normalize(cell)
    if not s:
        return ""
    # Strip parenthetical note at end, e.g., "Bill (maybe)"
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    # Take the first piece before common separators
    s = re.split(r"[,/&;]", s)[0]
    return s.strip()

def load_band_members(values):
    """
    Build maps from BandMembers worksheet values.
    Expected headers (case-insensitive): Name, Email|Email Address, Alias,
    Background, Foreground, Bold, Italic, Underline.
    Returns a dict with:
      - alias_to_full
      - full_to_email
      - key_to_style  (keyed by casefolded alias and full name)
      - token_style   (optional styles for 'yes','no','sub' if provided)
    """
    if not values:
        raise SystemExit("BandMembers tab is empty.")

    # Find header row
    header_idx = None
    header = []
    for i, row in enumerate(values[:10]):
        norm = [ (c or "").strip().lower() for c in row ]
        if "name" in norm and any(x in norm for x in ["email", "email address"]):
            header_idx = i
            header = row
            break
    if header_idx is None:
        raise SystemExit("BandMembers: couldn't find header row with 'Name' and 'Email'.")

    # Header map
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
        # Skip empty rows
        if not any((x or "").strip() for x in r):
            continue

        name  = _normalize(r[c_name])  if c_name  is not None and c_name  < len(r) else ""
        email = _normalize(r[c_email]) if c_email is not None and c_email < len(r) else ""
        alias = _normalize(r[c_alias]) if c_alias is not None and c_alias < len(r) else ""

        if not name:
            continue

        bg = _normalize(r[c_bg]) if c_bg is not None and c_bg < len(r) else ""
        fg = _normalize(r[c_fg]) if c_fg is not None and c_fg < len(r) else ""

        bold = _truthy(r[c_bold]) if c_bold is not None and c_bold < len(r) else False
        ital = _truthy(r[c_ital]) if c_ital is not None and c_ital < len(r) else False
        und  = _truthy(r[c_und])  if c_und  is not None and c_und  < len(r) else False

        style = {"bg": bg, "fg": fg, "bold": bold, "italic": ital, "underline": und}

        # Map full name → email
        if email:
            full_to_email[name] = email

        # Map alias → full name
        if alias:
            alias_to_full[alias] = name

        # Style by both keys (so you can match by alias or full)
        if name:
            key_to_style[_canon(name)] = style
        if alias:
            key_to_style[_canon(alias)] = style

        # Allow rows named "Yes", "No", "SUB" to style those tokens
        lower_name = name.strip().lower()
        if lower_name in {"yes", "no", "sub"}:
            token_style[lower_name] = style
        if alias.strip().lower() in {"yes", "no", "sub"}:
            token_style[alias.strip().lower()] = style

    return {
        "alias_to_full": alias_to_full,
        "full_to_email": full_to_email,
        "key_to_style": key_to_style,
        "token_style": token_style,
    }

# Fallback styles for Yes/No/SUB if not provided in sheet
FALLBACK_TOKEN_STYLE = {
    "yes": {"bg":"#ffffff","fg":"#f4557b","bold":False,"italic":False,"underline":True},
    "no":  {"bg":"#ffffff","fg":"#000000","bold":False,"italic":False,"underline":True},
    "sub": {"bg":"#ffffff","fg":"#f4557b","bold":True, "italic":False,"underline":True},
}

def style_css_from_spec(spec: dict) -> str:
    if not spec: return ""
    css = []
    if spec.get("bg"): css.append(f"background:{spec['bg']};")
    if spec.get("fg"): css.append(f"color:{spec['fg']};")
    if spec.get("bold"): css.append("font-weight:bold;")
    if spec.get("italic"): css.append("font-style:italic;")
    if spec.get("underline"): css.append("text-decoration:underline;")
    return "".join(css)

class MemberDirectory:
    """
    Encapsulates lookups:
      - find(full_or_alias_text) -> (full_name, alias_display)
      - style_for(cell_text) -> CSS inline style
      - email_for_full(full_name) -> email
    """
    def __init__(self, members_blob):
        self.alias_to_full = members_blob["alias_to_full"]
        self.full_to_email = members_blob["full_to_email"]
        self.key_to_style  = members_blob["key_to_style"]
        self.token_style   = members_blob["token_style"]

        # Build reverse: full → shortest alias (for display)
        rev = {}
        for a, f in self.alias_to_full.items():
            ca = a.strip()
            if f not in rev or len(ca) < len(rev[f]):
                rev[f] = ca
        self.full_to_alias = rev

    def email_for_full(self, full_name: str) -> str | None:
        return self.full_to_email.get(_normalize(full_name)) or None

    def find(self, cell_text: str) -> tuple[str|None, str]:
        """
        Returns (full_name, display_alias).
        If token is a special Yes/No/SUB, returns (None, token) — no email needed.
        """
        raw = _normalize(cell_text)
        if not raw:
            return (None, "")
        tok = _first_token(raw)
        if not tok:
            return (None, raw)

        low = tok.strip().lower()
        if low in {"yes","no","sub"}:
            return (None, tok)  # special token row; not a person

        # Match by alias first
        if tok in self.alias_to_full:
            full = self.alias_to_full[tok]
            return (full, tok)

        # Match by full name
        if tok in self.full_to_email:
            return (tok, self.full_to_alias.get(tok, tok))
        # case-insensitive scan over known full names
        for f in self.full_to_email.keys():
            if _canon(f) == _canon(tok):
                return (f, self.full_to_alias.get(f, tok))

        # No match; keep original token for display, but no email
        return (None, tok)

    def style_for(self, cell_text: str) -> str:
        raw = _normalize(cell_text)
        if not raw:
            return ""
        tok = _first_token(raw)
        if not tok:
            return ""
        low = tok.strip().lower()

        # Style for special tokens
        if low in {"yes","no","sub"}:
            spec = self.token_style.get(low) or FALLBACK_TOKEN_STYLE.get(low, {})
            return style_css_from_spec(spec)

        # Style for alias or name
        spec = self.key_to_style.get(_canon(tok), {})
        return style_css_from_spec(spec)

# ---------------- HTML TABLE ----------------
def html_table(rows, style_lookup):
    if not rows:
        return "<p>No gigs scheduled for the selected week.</p>"

    def esc(x):
        return str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

    header_bg = "#e6f2ff"  # light blue
    TABLE_MIN_PX = 900     # forces horizontal scroll on phones instead of microscopic columns

    # Column target widths
    COLW = {
        "date": "90px",
        "venue": "120px",
        "time": "100px",
        "location": "180px",
        "set": "60px",
        "pays": "70px",
        "role": "90px",  # per role col
    }

    # Base cell styles
    TD_BASE   = "padding:3px; vertical-align:middle; text-align:center; font-family:Arial,sans-serif; font-size:14px;"
    TD_WRAP20 = TD_BASE + "white-space:normal; word-break:break-word; overflow-wrap:anywhere;"
    TD_TIME   = TD_BASE + "white-space:normal;"
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

# ---------------- EMAIL BUILD/SEND ----------------
def build_message(subject, html, to_list):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = ", ".join(sorted(to_list))
    msg.attach(MIMEText(html, "html"))
    return {"raw": urlsafe_b64encode(msg.as_bytes()).decode("utf-8")}

def send_gmail(creds, body):
    svc = build("gmail", "v1", credentials=creds)
    backoff = 1.0
    attempts = 6
    for attempt in range(1, attempts + 1):
        try:
            return svc.users().messages().send(userId="me", body=body).execute()
        except HttpError as e:
            status = getattr(e, "resp", None).status if hasattr(e, "resp") else None
            txt = str(e)
            if status == 403 and "accessNotConfigured" in txt:
                raise SystemExit(
                    "Gmail API is disabled for your OAuth project.\n"
                    "Enable it in Google Cloud Console, wait a minute, and retry."
                )
            if status in RETRY_STATUS and attempt < attempts:
                sleep = backoff + random.uniform(0, 0.5)
                print(f"⚠️ Gmail {status}. Retrying in {sleep:.1f}s (attempt {attempt}/{attempts-1})…")
                time.sleep(sleep)
                backoff *= 2
                continue
            raise

# ---------------- PROMPTS ----------------
def prompt_beginning_sunday(default_start: date) -> date:
    """Prompt for beginning Sunday; Enter accepts default, else parse YYYY-MM-DD or 'this'/'next'."""
    disp = default_start.strftime("%a, %b %-d")
    while True:
        print(f"\nDefault beginning Sunday is {default_start} ({disp}).")
        inp = input("Press Enter to accept, type YYYY-MM-DD to change, or 'this'/'next': ").strip()
        if inp == "":
            return default_start
        if inp.lower() in ("this", "t"):
            today = datetime.now(gettz(TIMEZONE)).date()
            start, _ = week_range_sun_sat(today)
            return start
        if inp.lower() in ("next", "n"):
            today = datetime.now(gettz(TIMEZONE)).date()
            start, _ = next_week_sun_sat(today)
            return start
        try:
            base = pd.to_datetime(inp).to_pydatetime().date()
            start, _ = week_range_sun_sat(base)
            return start
        except Exception:
            print("Sorry, I couldn't parse that. Use YYYY-MM-DD (e.g., 2025-08-10), or 'this'/'next'.")

# ---------------- MAIN ----------------
def main():
    parser = argparse.ArgumentParser(description="Send Mixed Nuts weekly (Sun–Sat) gig email.")
    parser.add_argument("--test-only", action="store_true", help="Send only the test email to Keith.")
    parser.add_argument("--auto-send", action="store_true", help="Skip confirmation and send to full list after the test.")
    parser.add_argument("--this-week", action="store_true", help="Use the current Sun–Sat week (skips prompt).")
    parser.add_argument("--next-week", action="store_true", help="Use the next Sun–Sat week (skips prompt).")
    parser.add_argument("--week-of", type=str, metavar="YYYY-MM-DD", help="Any date; use the Sun–Sat week containing it (skips prompt).")
    parser.add_argument("--creds", type=str, default=None, help="Path to OAuth client secrets JSON (defaults beside script).")
    parser.add_argument("--token", type=str, default=None, help="Path to saved user token JSON (defaults beside script).")
    args = parser.parse_args()

    sheet_key = normalize_sheet_id(SHEET_ID)
    creds = get_credentials(args.creds, args.token)

    # Determine week start (Sunday), with interactive prompt unless a week flag is given
    today_local = datetime.now(gettz(TIMEZONE)).date()
    if args.week_of:
        base = pd.to_datetime(args.week_of).to_pydatetime().date()
        start, end = week_range_sun_sat(base)
    elif args.this_week:
        start, end = week_range_sun_sat(today_local)
    elif args.next_week:
        start, end = next_week_sun_sat(today_local)
    else:
        default_start, _ = next_week_sun_sat(today_local)
        start = prompt_beginning_sunday(default_start)
        end = start + timedelta(days=6)

    print(f"\n\nSelected week: {start.strftime('%a, %b %-d')} (Sun) – {(end).strftime('%a, %b %-d')} (Sat)")
    print(f"\n\nNow processing.  Please wait.")

    # Load schedule
    ws = open_ws(creds, sheet_key, SCHEDULE_TAB)
    values = with_retries(ws.get_all_values)
    if not values:
        raise SystemExit("Schedule tab is empty.")
    headers = [h.strip() for h in values[0]]
    rows = values[1:]

    def idx(pattern):
        return next(i for i,h in enumerate(headers) if re.search(pattern, h, re.I))

    idx_date  = idx(r"^date$")
    idx_venue = idx(r"^venue$")
    idx_time  = idx(r"^time$")
    idx_loc   = idx(r"^location$")
    idx_set   = idx(r"^set$")
    idx_pays  = idx(r"^pays$")
    idx_notes = next((i for i,h in enumerate(headers) if re.search(r"^notes$", h, re.I)), None)

    role_cols = {
        "vocal":  idx(r"^vocal$"),
        "piano":  idx(r"^piano$"),
        "bass":   idx(r"^bass$"),
        "drums":  idx(r"^drums$"),
        "guitar": idx(r"^guitar$"),
        "vibes":  idx(r"^vibes$"),
    }

    # Load roster + styles from BandMembers
    ws_m = open_ws(creds, sheet_key, MEMBERS_TAB)
    values_members = with_retries(ws_m.get_all_values)
    members_blob = load_band_members(values_members)
    directory = MemberDirectory(members_blob)

    # Filter to week + collect scheduled FULL names for email list
    week_rows = []
    scheduled_full_names = set()

    # NEW: track observed tokens by full name, and unmatched tokens for warnings
    tokens_by_full = {}      # dict[str, set[str]]
    unmatched_tokens = set() # set[str]

    for r in rows:
        d = parse_date(r[idx_date])
        if not d or not (start <= d <= end):
            continue
        entry = {
            "date": d,
            "date_disp": d.strftime("%a, %b %-d"),
            "venue": r[idx_venue],
            "time": r[idx_time],
            "location": r[idx_loc],
            "set": r[idx_set],
            "pays": r[idx_pays],
            "notes": r[idx_notes] if idx_notes is not None else "",
        }

        for role, c in role_cols.items():
            cell = r[c]
            full, alias_disp = directory.find(cell)
            entry[role] = alias_disp  # show alias (short name) in the grid

            # Remember token and matches
            tok = _first_token(cell)
            if full:
                tokens_by_full.setdefault(full, set()).add(tok)
                scheduled_full_names.add(full)
            else:
                if tok and tok.strip().lower() not in {"yes","no","sub"}:
                    unmatched_tokens.add(tok)

        week_rows.append(entry)

    week_rows.sort(key=lambda x: x["date"])

    # Build recipients: ALWAYS_INCLUDE + scheduled
    recipients_full = set()
    for nm in ALWAYS_INCLUDE:
        full, _ = directory.find(nm)  # allow either "Bill Marsh" or "Bill"
        if full:
            recipients_full.add(full)
        else:
            unmatched_tokens.add(nm)

    recipients_full |= scheduled_full_names

    # Build email list used for actual sending
    recipients = sorted({
        directory.email_for_full(n) for n in recipients_full
        if directory.email_for_full(n)
    })

    # Pretty listing with alias/full/email + flags
    def choose_alias_for_full(full: str) -> tuple[str, str | None]:
        """
        Returns (alias_to_show, warning_flag|None).
        Preference:
          1) An observed schedule token that is a valid alias for this full name.
          2) Any observed schedule token (even if not registered) -> flag.
          3) The registered alias for this full name (if exists).
          4) '(no alias)' -> flag.
        """
        observed = list(tokens_by_full.get(full, []))
        # 1) observed token that is a registered alias for *this* full person
        for tok in observed:
            if tok in directory.alias_to_full:
                mapped = directory.alias_to_full[tok]
                if mapped == full:
                    return tok, None
                else:
                    return tok, f"⚠ alias maps to {mapped}"

        # 2) observed token not registered as alias
        if observed:
            tok = sorted(observed)[0]
            if tok.lower() not in {"yes","no","sub"}:
                return tok, "⚠ alias not in BandMembers"

        # 3) fallback to registered alias from the directory
        fallback = directory.full_to_alias.get(full, "")
        if fallback:
            mapped = directory.alias_to_full.get(fallback)
            if mapped and mapped != full:
                return fallback, f"⚠ alias maps to {mapped}"
            return fallback, None

        # 4) no alias anywhere
        return "(no alias)", "⚠ no alias provided/found"

    print(f"\nPlanned recipients ({len(recipients_full)} people):")
    # Sort by last name, then first
    def name_key(n: str):
        parts = n.split()
        return (parts[-1].lower(), parts[0].lower() if parts else "")

    for full in sorted(recipients_full, key=name_key):
        alias, flag = choose_alias_for_full(full)
        email = directory.email_for_full(full)
        email_disp = email if email else "[NO EMAIL]"
        line = f" - {alias} — {full} — {email_disp}"
        if flag:
            line += f"   {flag}"
        if not email:
            line += "   ⚠ no email on file"
        print(line)

    if unmatched_tokens:
        print("\nUnmatched names/tokens in the schedule (no email will be sent to these):")
        for tok in sorted(unmatched_tokens, key=lambda s: s.lower()):
            print(f" - {tok}")

    if not recipients:
        print("\nNo deliverable emails found. Check BandMembers for emails/aliases.")
        return

    # ----- Build email body with greeting + optional comment -----
    comment = input("\nOptional comment to include (press Enter to skip): ").strip()
    comment_html = f"<p>{escape(comment).replace('\n', '<br>')}</p>" if comment else ""

    date_range = f"{start.strftime('%a, %b %-d')}–{end.strftime('%a, %b %-d, %Y')}"
    body_parts = [
        "<p>Hello Mixed Nuts,</p>",
        f"<p>Here is the schedule for the Mixed Nuts week of {date_range}:</p>",
        html_table(week_rows, style_lookup=directory.style_for),
        comment_html,
        "<p>– Keith</p>",
    ]
    html = "\n".join([part for part in body_parts if part])

    # Subject
    subject_core = f"Mixed Nuts week of {date_range}"

    # 1) Send TEST
    test_subject = f"[TEST] {subject_core}"
    send_gmail(creds, build_message(test_subject, html, [TEST_RECIPIENT]))
    print(f"✅ Test email sent to {TEST_RECIPIENT}")

    # Early exit if test-only
    if args.test_only:
        return

    # Confirm before full send
    go = "y" if args.auto_send else input("\nSend to full list now? (y/N): ").strip().lower()
    if go not in ("y", "yes"):
        print("Canceled. No group email sent.")
        return

    # 3) Send full
    send_gmail(creds, build_message(subject_core, html, recipients))
    print("📧 Sent to full list.")

if __name__ == "__main__":
    main()
