#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weekly_gig_reminder_email_v2.py
───────────────────────────────────────────────────────────────────────────────
Build the Mixed Nuts weekly gig email directly from Google Sheets, send a TEST
copy to Keith first, then (after Keith reviews) prompt to send to all recipients.

Enhancements vs v1:
  1) Verifies that the entered week-begin date is a Sunday and re-prompts if not.
  2) Improved comment prompt instructions explaining the EOF and short delay.
  3) Preserves all line breaks in multi-line comments.
  4) Adds an optional Tkinter text box editor for entering comments more easily.
"""

import re
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from html import escape

import pandas as pd
import gspread
from dateutil.tz import gettz
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from base64 import urlsafe_b64encode
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GARequest
from google.auth.exceptions import RefreshError

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

CREDS_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
TOKEN_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.json"

SHEET_ID     = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB = "CurrentYrSched"
MEMBERS_TAB  = "BandMembers"

TIMEZONE    = "America/Denver"
KEITH_EMAIL = "keith.day@legacyperformers.org"

SIGNOFF_HTML = "<p>Best,</p><p>- Keith</p>"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

ALWAYS_INCLUDE = {"Bill Marsh", "Jay Christensen", "Katie Blunt"}

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    return (s or "").strip()

def _canon(s: str) -> str:
    return _normalize(s).casefold()

def _truthy(s: str) -> bool:
    return str(s).strip().lower() in {"1","true","yes","y","t"}

def _first_token(cell: str) -> str:
    s = _normalize(cell)
    if not s:
        return ""
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return re.split(r"[,/&;]", s)[0].strip()

def _clean_header(h: str) -> str:
    return re.sub(r"\s+", " ", (h or "").strip().strip('"').strip("'"))

# ──────────────────────────────────────────────────────────────────────────────
# Comment input utilities
# ──────────────────────────────────────────────────────────────────────────────

def read_multiline_input(prompt: str, end_marker: str = "EOF") -> str:
    """
    Read multi-line input from the terminal until a line that equals end_marker.
    Returns the joined text (without the final marker line).
    If the user just presses Enter at the first prompt, returns "".
    """
    print(prompt)
    first = input().rstrip("\n")
    if first.strip() == "":
        return ""  # user pressed Enter immediately -> no comment
    if first.strip() == end_marker:
        return ""  # user entered EOF immediately

    lines = [first]
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == end_marker:
            break
        lines.append(line)
    return "\n".join(lines)

def read_multiline_input_gui(title="Enter comment for weekly email") -> str:
    """
    Opens a small Tkinter text box for typing a multi-line comment.
    Returns the entered text, preserving all line breaks.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as e:
        print(f"(Tkinter not available: {e})")
        return ""

    result = {"text": ""}

    def on_submit():
        result["text"] = text.get("1.0", "end-1c")
        root.destroy()

    def on_cancel():
        result["text"] = ""
        root.destroy()

    root = tk.Tk()
    root.title(title)
    root.geometry("700x400")
    root.resizable(True, True)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill="both", expand=True)

    lbl = ttk.Label(frm, text="Type your comment below. Line breaks will be preserved in the email:")
    lbl.pack(anchor="w", pady=(0,5))

    text = tk.Text(frm, wrap="word", font=("Arial", 12))
    text.pack(fill="both", expand=True)

    btn_frame = ttk.Frame(frm)
    btn_frame.pack(fill="x", pady=(10,0))
    ttk.Button(btn_frame, text="OK", command=on_submit).pack(side="left", padx=(0,5))
    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="left")

    root.mainloop()
    return result["text"].strip()

# ──────────────────────────────────────────────────────────────────────────────
# Safe yes/no prompt
# ──────────────────────────────────────────────────────────────────────────────

def prompt_yes_no(prompt: str) -> bool:
    """Prompt for y/n and ignore blank lines or stray input until valid."""
    while True:
        ans = input(prompt).strip().lower()
        if ans in ("y", "n"):
            return ans == "y"

# ──────────────────────────────────────────────────────────────────────────────
# HTML helpers
# ──────────────────────────────────────────────────────────────────────────────

def normalize_signoff(body_html: str) -> str:
    s = body_html
    s = re.sub(r"\s*(?:<p>\s*Best,\s*</p>\s*)+", "", s, flags=re.IGNORECASE)
    dash_group = r"(?:&mdash;|&ndash;|—|–|-)"
    nbsp_or_space = r"(?:&nbsp;|\s)?"
    s = re.sub(rf"\s*(?:<p>\s*{dash_group}\s*{nbsp_or_space}Keith\s*</p>\s*)+", "", s, flags=re.IGNORECASE)
    s = re.sub(rf"(?:<br\s*/?>|\n|\r)?\s*{dash_group}\s*{nbsp_or_space}Keith\s*(?=(?:<br\s*/?>|\n|\r|$))", "", s, flags=re.IGNORECASE)
    s = re.sub(r"(?:\s*<p>\s*</p>\s*)+", "", s, flags=re.IGNORECASE).strip()
    return s + SIGNOFF_HTML

def inject_comment_before_signoff(body_html: str, comment_text: str) -> str:
    comment_text = (comment_text or "").strip()
    if not comment_text:
        return body_html
    comment_html = f"<p>{escape(comment_text).replace('\n', '<br>')}</p>"
    patterns = [
        r"(<p>\s*Best,\s*</p>\s*<p>\s*(?:&mdash;|&ndash;|—|–|-)\s*(&nbsp;)?\s*Keith\s*</p>)",
        r"(<p>\s*(?:&mdash;|&ndash;|—|–|-)\s*(&nbsp;)?\s*Keith\s*</p>)",
    ]
    for pat in patterns:
        m = re.search(pat, body_html, flags=re.IGNORECASE)
        if m:
            return body_html[:m.start()] + comment_html + body_html[m.start():]
    return body_html + comment_html

# ──────────────────────────────────────────────────────────────────────────────
# Band members & styling
# ──────────────────────────────────────────────────────────────────────────────

def style_css_from_spec(spec: dict) -> str:
    if not spec:
        return ""
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

# ──────────────────────────────────────────────────────────────────────────────
# Gmail / HTML table
# ──────────────────────────────────────────────────────────────────────────────

def stack_time_cell(s: str) -> str:
    if not s: return ""
    return re.sub(r"\s*[\-–]\s*", " –<br>", str(s).strip(), count=1)

def html_table(rows, style_lookup):
    if not rows:
        return "<p>No gigs scheduled for the selected week.</p>"
    def esc(x): return str(x).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    header_bg = "#e6f2ff"
    TABLE_MIN_PX = 900
    TD_BASE = "padding:3px; vertical-align:middle; text-align:center; font-family:Arial,sans-serif; font-size:14px;"
    head = ("Date","Venue","Time","Location","Set","Pays","Vocal","Piano","Bass","Drums","Guitar","Vibes")
    s = [f"<div style='width:100%; overflow-x:auto;'>"]
    s.append(f"<table border='1' cellpadding='3' cellspacing='0' style='border-collapse:collapse; min-width:{TABLE_MIN_PX}px;'>")
    s.append(f"<tr style='font-weight:bold; background:{header_bg}'>" + "".join(f"<td style='{TD_BASE}'>{h}</td>" for h in head) + "</tr>")
    for r in rows:
        def role_td(v): return f"<td style='{TD_BASE}{style_lookup(v)}'>{esc(v)}</td>"
        s.append("<tr>" +
                 "".join([
                     f"<td style='{TD_BASE}'>{esc(r['date_disp'])}</td>",
                     f"<td style='{TD_BASE}'>{esc(r['venue'])}</td>",
                     f"<td style='{TD_BASE}'>{stack_time_cell(r.get('time',''))}</td>",
                     f"<td style='{TD_BASE}'>{esc(r['location'])}</td>",
                     f"<td style='{TD_BASE}'>{esc(r.get('set',''))}</td>",
                     f"<td style='{TD_BASE}'>{esc(r.get('pays',''))}</td>",
                     role_td(r.get('vocal','')), role_td(r.get('piano','')), role_td(r.get('bass','')),
                     role_td(r.get('drums','')), role_td(r.get('guitar','')), role_td(r.get('vibes',''))
                 ]) + "</tr>")
    s.append("</table></div>")
    return "\n".join(s)

def get_credentials():
    token_path = Path(TOKEN_PATH)
    creds_path = Path(CREDS_PATH)
    creds = None
    if token_path.exists():
        try: creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception: token_path.unlink(missing_ok=True)
    if creds and creds.valid: return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(GARequest())
            return creds
        except RefreshError:
            pass
    import sys
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SystemExit("Run interactively once to refresh OAuth.")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds

def open_ws(creds, sheet_key, tab):
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_key).worksheet(tab)

def build_message(subject, html, to_list):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = ", ".join(sorted(to_list))
    msg.attach(MIMEText(html, "html"))
    return {"raw": urlsafe_b64encode(msg.as_bytes()).decode("utf-8")}

def send_gmail(creds, body):
    return build("gmail", "v1", credentials=creds).users().messages().send(userId="me", body=body).execute()

# ──────────────────────────────────────────────────────────────────────────────
# Schedule reading and email assembly
# ──────────────────────────────────────────────────────────────────────────────

def week_range(date_in: date):
    days_since_sun = (date_in.weekday() + 1) % 7
    sunday = date_in - timedelta(days=days_since_sun)
    return sunday, sunday + timedelta(days=6)

def next_week_range(today: date):
    this_sun, _ = week_range(today)
    next_sun = this_sun + timedelta(days=7)
    return next_sun, next_sun + timedelta(days=6)

def read_week_rows(creds, start: date, end: date):
    ws = open_ws(creds, SHEET_ID, SCHEDULE_TAB)
    values = ws.get_all_values()
    if not values: return [], {}
    headers, rows = values[0], values[1:]
    clean_headers = [_clean_header(h) for h in headers]
    def idx(pat): return next((i for i,h in enumerate(clean_headers) if re.fullmatch(pat,h,re.I)), None)
    idx_date, idx_venue, idx_time, idx_loc = idx("date"), idx("venue"), idx("time"), idx("location")
    idx_set, idx_pays = idx("set"), idx("pays?")
    idx_vocal, idx_piano, idx_bass, idx_drums, idx_guitar, idx_vibes = idx("vocal(s)?"), idx("(piano|keys?|keyboard)"), idx("bass"), idx("drum(s)?"), idx("guitar"), idx("(vibes?|vibraphone)")
    def val(r,i): return r[i] if i is not None and i < len(r) else ""
    week_rows = []
    for r in rows:
        d_ts = pd.to_datetime(val(r,idx_date), errors="coerce")
        if pd.isna(d_ts): continue
        d = d_ts.date()
        if start <= d <= end:
            week_rows.append({
                "date_disp": d.strftime("%a, %b %-d"),"venue":val(r,idx_venue),"time":val(r,idx_time),
                "location":val(r,idx_loc),"set":val(r,idx_set),"pays":val(r,idx_pays),
                "vocal":val(r,idx_vocal),"piano":val(r,idx_piano),"bass":val(r,idx_bass),
                "drums":val(r,idx_drums),"guitar":val(r,idx_guitar),"vibes":val(r,idx_vibes)})
    return week_rows, {}

def build_email_html(week_rows, members_blob, start: date, end: date, comment: str):
    date_range = f"{start.strftime('%a, %b %-d')} to {end.strftime('%a, %b %-d, %Y')}"
    subject = f"Mixed Nuts week of {date_range}"
    body_html = (
        "<p>Hello Mixed Nuts,</p>"
        f"<p>Here is the schedule for the week of {date_range}:</p>"
        f"{html_table(week_rows, lambda v: style_for(v, members_blob['key_to_style'], members_blob['token_style']))}"
    )
    body_html = normalize_signoff(body_html)
    body_html = inject_comment_before_signoff(body_html, comment)
    return subject, body_html

def collect_recipients(week_rows, members_blob):
    alias_to_full, full_to_email = members_blob["alias_to_full"], members_blob["full_to_email"]
    scheduled = set()
    for r in week_rows:
        for role in ("vocal","piano","bass","drums","guitar","vibes"):
            full = resolve_full_name(r.get(role,""), alias_to_full, full_to_email)
            if full: scheduled.add(full)
    for nm in ALWAYS_INCLUDE:
        full = resolve_full_name(nm, alias_to_full, full_to_email) or nm
        if full: scheduled.add(full)
    return sorted({full_to_email.get(f) for f in scheduled if full_to_email.get(f)}, key=str.lower)

# ──────────────────────────────────────────────────────────────────────────────
# Main CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week-of", type=str, default=None)
    args = parser.parse_args()

    creds = get_credentials()
    tz = gettz(TIMEZONE)
    today = datetime.now(tz).date()
    next_sunday, _ = next_week_range(today)

    print("\nMixed Nuts Weekly Gig Mailer (Review → Confirm Send)")
    print("-----------------------------------------------------")
    print(f"Default week begins on Sunday: {next_sunday.strftime('%Y-%m-%d')}")

    # Require Sunday date input
    while True:
        user_input = input("Enter week beginning date (YYYY-MM-DD) or press Enter for default: ").strip()
        if not user_input:
            week_start, week_end = week_range(next_sunday)
            break
        try:
            base = pd.to_datetime(user_input).date()
        except Exception:
            print("❌ Invalid date format. Please use YYYY-MM-DD.")
            continue
        if base.weekday() != 6:  # Sunday check
            print(f"⚠️  {base.strftime('%A')} is not a Sunday. Please enter a Sunday date.")
            continue
        week_start, week_end = week_range(base)
        break

    print("\nEnter any comments to include before sign-off.")
    print("• Press Enter on a blank line if you have no comment.")
    print("• Or type multiple lines below, ending with exactly 'EOF' on its own line.")
    print("  (After entering 'EOF', please wait a few seconds while the program processes it.)\n")

    use_gui = prompt_yes_no("Would you like to open a comment editor window? (y/n): ")

    if use_gui:
        comment = read_multiline_input_gui().strip()
    else:
        comment = read_multiline_input("Comment (end with EOF):", end_marker="EOF").strip()

    week_rows, _ = read_week_rows(creds, week_start, week_end)
    ws_m = open_ws(creds, SHEET_ID, MEMBERS_TAB)
    members_blob = load_band_members(ws_m.get_all_values())

    subject, body_html = build_email_html(week_rows, members_blob, week_start, week_end, comment)
    recipients = collect_recipients(week_rows, members_blob)
    if KEITH_EMAIL not in recipients:
        recipients.append(KEITH_EMAIL)
        recipients = sorted(set(recipients), key=str.lower)

    # Send TEST email
    test_subject = f"[TEST] {subject}"
    send_gmail(creds, build_message(test_subject, body_html, [KEITH_EMAIL]))
    print(f"\n📧 Sent TEST email to {KEITH_EMAIL}.")
    print("   Please review it in your Sent Mail box before confirming.\n")

    # Confirmation
    print("Final recipients to be emailed (excluding the [TEST] prefix):")
    for i, addr in enumerate(recipients, start=1):
        print(f"  {i}. {addr}")
    print(f"\nSubject: {subject}")
    if not prompt_yes_no("Send this email to all recipients listed above? (y/n): "):
        print("❌ Aborted. No emails sent.")
        return

    if not recipients:
        print("❌ No recipients found. Aborting.")
        return

    send_gmail(creds, build_message(subject, body_html, recipients))
    print(f"✅ Sent FINAL email to {len(recipients)} recipients.")

if __name__ == "__main__":
    main()
