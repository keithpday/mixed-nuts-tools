#!/usr/bin/env python3
"""
Report Twilio texts over a local date range (America/Denver),
listing ALL messages per person (inbound + outbound), enriched with BandMembers.

- Prompts: "How many days back?" (0=today only; 1=yesterday+today; etc.)
- Uses local dates (America/Denver), converts to UTC for Twilio API query.
- Groups by counterparty (the *other* phone): inbound -> From, outbound -> To.
- Prints every message (oldest → newest) with FULL body text.
- Exceptions section for any status not 'delivered' (failed/undelivered).
- Summary with per-status counts.
- Prints a terminal STATUS line and sets exit code:
    0 = OK (no failed/undelivered)
    2 = WARN (has failed/undelivered)
    1 = error running script

BandMembers requirements:
- Required columns: Alias, Phone
- Optional name columns: "Full Name" OR "Name" OR ("First Name" and/or "Last Name")

NOTE: If you later want to filter back to just your "Auto reminder" texts,
      uncomment the line marked  >>> AUTO-REMINDER FILTER <<<  below.

NOTE: If you later want to restrict to a specific sending number, set FILTER_SENDER
      to your +E.164 and uncomment the block marked  >>> SENDER FILTER <<<.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter
import re
import sys

import gspread
from google.oauth2.service_account import Credentials
from twilio.rest import Client
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ---------------- Twilio + Sheets config ----------------
TWILIO_SID  = os.getenv("TWILIO_SID", "")
TWILIO_AUTH = os.getenv("TWILIO_AUTH", "")
FILTER_SENDER = os.getenv("FILTER_SENDER")  # optional, default None

SERVICE_ACCOUNT_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
SHEET_ID             = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
MEMBERS_TAB          = "BandMembers"
SCOPES               = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

LOCAL_TZ = ZoneInfo("America/Denver")
SEP = "=" * 80  # 80-char visual separator

# Common Twilio error codes → friendly text (not exhaustive, covers typical cases)
ERROR_MAP = {
    # Twilio REST/API level (21xxx)
    "21610": "Recipient opted out (STOP).",
    "21614": "Invalid destination phone number.",
    "21612": "Recipient not capable of receiving SMS/MMS.",
    "21608": "Configured sender not SMS-capable.",
    # Carrier delivery receipts (3000x)
    "30001": "Carrier queue overflow.",
    "30002": "Carrier/account suspended.",
    "30003": "Unreachable/unavailable handset.",
    "30004": "Message blocked by carrier.",
    "30005": "Unknown destination handset.",
    "30006": "Landline or unreachable destination.",
    "30007": "Carrier filtering (campaign/content).",
    "30008": "Unknown carrier error.",
    "30010": "Message content/length/rate issue.",
}

def explain_error(code: str | None) -> str:
    if not code:
        return ""
    c = str(code)
    if c in ERROR_MAP:
        return ERROR_MAP[c]
    if c.startswith("216"):
        return "Number/opt-out/capability issue."
    if c.startswith("300"):
        return "Carrier delivery failure."
    return "Unspecified error."

# ---------------- Helpers ----------------
def normalize_phone(p: str) -> str:
    """North America best-effort. Keep digits; add +1 for 10-digit; keep leading + if present."""
    if not p:
        return ""
    p = str(p).strip()
    if p.startswith("+"):
        return p
    digits = re.sub(r"\D+", "", p)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return p

def prompt_lookback_days(default_val: int = 0) -> int:
    raw = input(f"How many days back? (0=today only) [default {default_val}]: ").strip()
    if not raw:
        return default_val
    try:
        n = int(raw)
        if n < 0:
            print("  ⚠️ Negative not allowed; using 0.")
            return 0
        return n
    except ValueError:
        print("  ⚠️ Not an integer; using default 0.")
        return default_val

def local_range_utc(lookback_days: int):
    """Return (start_utc, end_utc, start_local_date, end_local_date) for local-midnight window."""
    now_local = datetime.now(LOCAL_TZ)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=lookback_days)
    end_local   = now_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return (start_local.astimezone(timezone.utc),
            end_local.astimezone(timezone.utc),
            start_local.date(),
            (end_local - timedelta(seconds=1)).date())

def load_member_directory():
    """Load BandMembers into maps by phone and alias."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SHEET_ID).worksheet(MEMBERS_TAB)
    rows = ws.get_all_records()

    by_phone = {}  # "+1XXXXXXXXXX" -> {"alias": ..., "full_name": ...}

    for r in rows:
        alias = str(r.get("Alias", "")).strip()
        phone = normalize_phone(r.get("Phone", ""))
        if not alias and not phone:
            continue

        # Construct a full name from any of these fields
        full_name = (str(r.get("Full Name", "")).strip()
                     or str(r.get("Name", "")).strip())
        if not full_name:
            first = str(r.get("First Name", "")).strip()
            last  = str(r.get("Last Name", "")).strip()
            if first or last:
                full_name = (first + " " + last).strip()

        entry = {
            "alias": alias or "",
            "full_name": full_name or "",
            "phone": phone or "",
        }

        if phone:
            by_phone[phone] = entry

    return by_phone

def msg_timestamp(m):
    """Best-effort timestamp for any message (outbound/inbound)."""
    # Some inbound messages may not have date_sent; fall back to created/updated.
    return m.date_sent or m.date_created or m.date_updated

# ---------------- Main ----------------
def main():
    try:
        lookback = prompt_lookback_days(default_val=0)
        start_utc, end_utc, start_local_date, end_local_date = local_range_utc(lookback)

        by_phone = load_member_directory()

        client = Client(TWILIO_SID, TWILIO_AUTH)

        list_kwargs = {
            "date_sent_after": start_utc,
            "date_sent_before": end_utc,
            "page_size": 1000,
        }
        # >>> SENDER FILTER <<<  (uncomment to restrict to one sending number)
        # if FILTER_SENDER:
        #     list_kwargs["from_"] = FILTER_SENDER

        msgs = client.messages.list(**list_kwargs)

        # >>> AUTO-REMINDER FILTER <<<  (uncomment to see only your reminder texts)
        # msgs = [m for m in msgs if (m.body or "").startswith("Auto reminder:")]

        print(f"\n=== All messages for {start_local_date} .. {end_local_date} (America/Denver) — grouped by person ===\n")

        if not msgs:
            print("No messages found in this range.")
            print(f"STATUS: OK — recipients=0 messages=0 exceptions=0 range={start_local_date}..{end_local_date}")
            return 0

        # Group by counterparty phone: inbound -> From; outbound -> To
        by_party = defaultdict(list)
        for m in msgs:
            direction = (m.direction or "").lower()
            if direction.startswith("inbound"):
                party = normalize_phone(m.from_)
            else:
                party = normalize_phone(m.to)
            by_party[party].append(m)

        status_counts = Counter()
        exceptions = []  # (party, alias, full_name, status, error_code, sid, ts)

        # Print each person and ALL their messages (oldest→newest), with enrichment
        for party in sorted(by_party.keys()):
            info = by_phone.get(party, {})
            alias = info.get("alias") or "?"
            full_name = info.get("full_name") or "?"

            items = by_party[party]
            items.sort(key=lambda x: msg_timestamp(x) or start_utc)  # oldest..newest

            print(f"{party} — {len(items)} message(s) — Alias: {alias} — Name: {full_name}")

            for m in items:
                ts = msg_timestamp(m)
                ts_local = ts.astimezone(LOCAL_TZ) if ts else None
                body_full = (m.body or "").rstrip()
                err_code = m.error_code or ""
                err_text = explain_error(err_code)
                err_part = f"err={err_code} {('('+err_text+')') if err_text else ''}".strip()
                direction = m.direction or ""

                print(f"   {ts_local}  {m.status:>11}  {direction:>13}  {err_part}  {m.sid}")
                print(f"      {body_full}")
                status_counts[m.status] += 1
                if m.status in ("failed", "undelivered"):
                    exceptions.append((party, alias, full_name, m.status, err_code, m.sid, ts_local))

            # separator after this person's section
            print(SEP)

        # Exceptions (not delivered)
        if exceptions:
            print("\n--- Exceptions (failed/undelivered) ---")
            for party, alias, full_name, st, err, sid, ts in exceptions:
                friendly = explain_error(err) if err else ""
                suffix = f" ({friendly})" if friendly else ""
                print(f"{party:>14}  {st:>11}  err={err or 'n/a'}{suffix}  {ts}  {sid}  Alias={alias}  Name={full_name}")
        else:
            print("\n(no exceptions — all messages delivered/sent/received)")

        # Summary + STATUS line
        total_recipients = len(by_party)
        total_msgs = len(msgs)
        failed = status_counts.get("failed", 0)
        undeliv = status_counts.get("undelivered", 0)
        exceptions_count = failed + undeliv

        print("\n--- Summary ---")
        print(f"Recipients: {total_recipients}   Messages: {total_msgs}")
        for st in sorted(status_counts.keys()):
            print(f"  {st:>11}: {status_counts[st]}")

        if exceptions_count > 0:
            print(f"\nSTATUS: WARN — recipients={total_recipients} messages={total_msgs} exceptions={exceptions_count} range={start_local_date}..{end_local_date}")
            return 2
        else:
            print(f"\nSTATUS: OK — recipients={total_recipients} messages={total_msgs} exceptions=0 range={start_local_date}..{end_local_date}")
            return 0

    except Exception as e:
        print(f"ERROR: {e}")
        print("STATUS: ERROR — see above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
