#!/usr/bin/env python3
import os
import re
from datetime import datetime, date, timedelta
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv


# ---------------- CONFIG ----------------
# Twilio credentials (hardcoded here)
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Twilio credentials (from environment)
TWILIO_SID  = os.getenv("TWILIO_SID", "")
TWILIO_AUTH = os.getenv("TWILIO_AUTH", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")


# Google Sheets config
SERVICE_ACCOUNT_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
SHEET_ID = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
SCHEDULE_TAB = "CurrentYrSched"
MEMBERS_TAB  = "BandMembers"
TIMEZONE = "America/Denver"

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

ROLE_COLS = ["Vocal", "Piano", "Bass", "Drums", "Guitar", "Vibes"]

def _assert_twilio_creds(sid: str, token: str):
    if not re.fullmatch(r"AC[a-fA-F0-9]{32}", sid or ""):
        raise ValueError(f"TWILIO_SID looks malformed: {repr(sid)}")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", token or ""):
        raise ValueError("TWILIO_AUTH looks malformed (should be 32 hex chars).")

_assert_twilio_creds(TWILIO_SID, TWILIO_AUTH)

def validate_twilio_login():
    from twilio.rest import Client
    c = Client(TWILIO_SID, TWILIO_AUTH)
    try:
        acct = c.api.accounts(TWILIO_SID).fetch()
        print(f"🔐 Twilio auth OK — account: {acct.friendly_name} (status: {acct.status})")
        return True
    except TwilioException as e:
        print("❌ Twilio auth FAILED:", e)
        return False

# ---------------- HELPERS ----------------
def parse_sheet_date(raw) -> date | None:
    """Parse a Sheets date (string/int serial/ISO) into a Python date."""
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

    # Excel/Sheets serial date
    if s.isdigit():
        try:
            base = date(1899, 12, 30)
            return base + timedelta(days=int(s))
        except Exception:
            return None
    return None

def require_twilio_creds():
    missing = []
    if not TWILIO_SID:  missing.append("TWILIO_SID")
    if not TWILIO_AUTH: missing.append("TWILIO_AUTH")
    if not TWILIO_FROM: missing.append("TWILIO_FROM")
    if missing:
        raise RuntimeError(
            "Missing Twilio credentials: " + ", ".join(missing) +
            "\nSet them, e.g.:\n"
            "  export TWILIO_SID='ACxxxxxxxx...'\n"
            "  export TWILIO_AUTH='your_auth_token'\n"
            "  export TWILIO_FROM='+18015551234'\n"
        )

def normalize_phone(p: str) -> str:
    """North American best-effort: keep digits; add +1 if 10 digits; preserve leading +."""
    if not p:
        return ""
    digits = re.sub(r"\D+", "", p)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return p.strip()  # fallback (could already be +E.164)


def send_sms(to_number: str, message: str):
    """Send an SMS using Twilio."""
    to_number_norm = normalize_phone(to_number)
    from_norm = normalize_phone(TWILIO_FROM)

    if not to_number_norm:
        print("⚠️  Skipping: empty phone number.")
        return

    # NEW: don't text the same number we're sending from
    if to_number_norm == from_norm:
        print(f"⚠️  Skipping: 'to' equals TWILIO_FROM ({to_number_norm}).")
        return

    client = Client(TWILIO_SID, TWILIO_AUTH)
    msg = client.messages.create(
        body=message,
        messaging_service_sid="MG81a390670c0353923237a9b72cdfc3e5",
        to=to_number_norm
    )
    print(f"✅ Sent to {to_number_norm}: {msg.sid}")

def load_member_directory(gc):
    """
    Load BandMembers → dict keyed by lowercased Alias:
      { alias_lc: {"Alias": ..., "Email": ..., "Phone": ...} }
    Required columns in BandMembers: Alias, Email Address, Phone
    """
    ws = gc.open_by_key(SHEET_ID).worksheet(MEMBERS_TAB)
    rows = ws.get_all_records()
    directory = {}
    for r in rows:
        alias = str(r.get("Alias", "")).strip()
        email = str(r.get("Email Address", "")).strip()
        phone = str(r.get("Phone", "")).strip()
        if alias:  # allow empty phone/email; we’ll warn later
            directory[alias.lower()] = {
                "Alias": alias,
                "Email": email,
                "Phone": phone,
            }
    return directory

_SPLIT_RE = re.compile(r"\s*(?:,|/|&| and )\s*", flags=re.IGNORECASE)

def extract_aliases_from_row(row: dict) -> list[str]:
    """Collect all aliases from the role columns, split if multiple names given."""
    found = []
    for col in ROLE_COLS:
        raw = str(row.get(col, "") or "").strip()
        if not raw:
            continue
        # Remove simple notes like "(sub)" or extra spaces
        raw = re.sub(r"\([^)]*\)", "", raw).strip()
        parts = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()]
        found.extend(parts)
    return found

# ---------------- MAIN ----------------
def main():
    if not validate_twilio_login():
        return
    
    today_local = date.today()
    print(f"Checking date {today_local}")

    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)

    sched_ws = gc.open_by_key(SHEET_ID).worksheet(SCHEDULE_TAB)
    schedule_rows = sched_ws.get_all_records()

    directory = load_member_directory(gc)

    any_row_today = False
    for row in schedule_rows:
        row_date = parse_sheet_date(row.get("Date"))
        ##print(f"Checking row dated {row_date}")

        if row_date != today_local:
            continue

        any_row_today = True

        # Message text
        time_ = str(row.get("Time", "") or "").strip()
        venue = str(row.get("Venue", "") or "").strip()
        location = str(row.get("Location", "") or "").strip()
        message = f"Auto reminder: You have a gig today at {venue} ({time_}) {location}.\n—Mixed Nuts"

        # Gather aliases from the role columns
        aliases = extract_aliases_from_row(row)
        if not aliases:
            print("⚠️  No musician aliases found in role columns for this row.")
            continue

        sent_to = set()
        for alias in aliases:
            key = alias.lower()
            info = directory.get(key)
            if not info:
                print(f"⚠️  Alias not found in BandMembers → '{alias}'")
                continue

            phone = info.get("Phone", "").strip()
            if not phone:
                print(f"⚠️  Missing phone for alias '{alias}' in BandMembers.")
                continue

            # Avoid duplicate texts if the same person appears twice
            unique_key = (info["Alias"].lower(), phone)
            if unique_key in sent_to:
                continue

            send_sms(phone, message)
            sent_to.add(unique_key)

        if sent_to:
            print(f"Found a gig today; notified: {', '.join(sorted({a for a,_ in sent_to}))}")
            print(f"✅ Message sent: {message}")
        else:
            print("⚠️  No notifications sent for this row (missing/mismatched phones/aliases).")

    if not any_row_today:
        print("No gigs found for today.")
    print("All schedule rows checked. Process completed")

if __name__ == "__main__":
    main()
