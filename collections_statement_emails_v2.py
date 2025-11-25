#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collections_statement_emails_v2.py
───────────────────────────────────────────────────────────────────────────────
Version 2.0 — November 20, 2025
Author: Keith Day

Purpose:
    Generate and send professional HTML-only collections statement emails
    to venues with open invoices, drawing data directly from the "BkdDts" tab
    (and using pre-calculated balances) in a Google Sheet.

    This version REMOVES all dependency on the "Rcvbles" tab. It assumes:
      • Each booking in BkdDts has a unique "Invoice Number".
      • "Invoice Balance Due" contains the current balance for that invoice.
      • "Collection Notes" is where we append dated notes on statements sent.
      • "Contact Email" is the email destination for the venue.
      • "Attachment" holds a Google Drive link to the invoice PDF (optional).

Key Behaviors:
    • Authenticates once (token caching) using credentials.json.
    • Reads booking/invoice data from BkdDts only.
    • Groups open invoices by Performance Venue.
    • A venue qualifies if ANY invoice age ≥ min_days_late; once qualified,
      ALL unpaid invoices (positive balance) for that venue are included.
    • Builds branded HTML email bodies with professional styling.
    • Downloads and attaches matching PDF invoices from Google Drive.
    • Prompts before sending each email with venue summary and oldest age.
    • Sends via Gmail API (HTML multipart only).
    • Appends a dated "Sent Collections Statement" note in BkdDts!
      Collection Notes (AO) for all included invoices when in Final mode.
    • Outputs local HTML copies of all generated messages in ./output/emails.
───────────────────────────────────────────────────────────────────────────────
"""

import os
import re
import io
import sys
import time
import base64
import pathlib
import argparse
import datetime as dt
from collections import defaultdict

from dateutil import tz
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

PROGRAM_NAME = pathlib.Path(__file__).stem
DEFAULT_CREDENTIALS_FILE = os.environ.get(
    "GOOGLE_OAUTH_CLIENT",
    "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json",
)
_default_token_path = pathlib.Path(DEFAULT_CREDENTIALS_FILE).with_name(
    f"{PROGRAM_NAME}.json"
)
TOKEN_FILE = os.environ.get("GOOGLE_OAUTH_TOKEN", str(_default_token_path))

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

OUTPUT_DIR = pathlib.Path("./output/emails")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# This is the base date used to derive invoice dates from the numeric prefix
# of the invoice number, e.g., 471LHOT → START_DATE + (471 - 1) days.
START_DATE = dt.date(2023, 11, 7)

# ──────────────────────────────────────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────────────────────────────────────


def numeric_prefix(s: str):
    m = re.match(r"(\d+)", str(s))
    return int(m.group(1)) if m else None


def date_from_invoice(docnbr: str):
    """Convert numeric prefix of invoice number into a date based on START_DATE."""
    n = numeric_prefix(docnbr)
    if n is None:
        return None
    return START_DATE + dt.timedelta(days=(n - 1))


def parse_sheet_date(raw: str):
    """Best-effort parsing of a BkdDts date string (Performance Date fallback)."""
    if not raw:
        return None
    text = str(raw).strip()
    # Try a couple of common formats
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # If Google Sheets stores numeric serials and they end up here,
    # you could extend this to handle that; for now, return None on failure.
    return None


def safe_float(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return 0.0


def today_str():
    return dt.datetime.now(tz=tz.gettz("America/Denver")).strftime("%Y-%m-%d")


def prompt_yes_no(prompt_text: str) -> bool:
    while True:
        ans = input(prompt_text).strip().lower()
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False
        print("Please enter Y or N.")


# ──────────────────────────────────────────────────────────────────────────────
# OAuth setup (cached)
# ──────────────────────────────────────────────────────────────────────────────


def get_services(credentials_path: str, token_path: str, debug=False):
    credspath = pathlib.Path(credentials_path)
    if not credspath.exists():
        raise FileNotFoundError(f"Credentials file not found: {credspath}")

    tokenp = pathlib.Path(token_path)
    tokenp.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if tokenp.exists():
        creds = Credentials.from_authorized_user_file(str(tokenp), SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(credspath), SCOPES)
        creds = flow.run_local_server(port=0)
        with open(tokenp, "w") as f:
            f.write(creds.to_json())
        if debug:
            print(f"[DEBUG] Saved OAuth token to: {tokenp}")

    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    gmail = build("gmail", "v1", credentials=creds)
    return sheets, drive, gmail


# ──────────────────────────────────────────────────────────────────────────────
# Google Sheets helpers
# ──────────────────────────────────────────────────────────────────────────────


def read_sheet_as_dicts(sheets_svc, spreadsheet_id, tab_name, debug=False):
    rng = f"{tab_name}!A:ZZ"
    resp = (
        sheets_svc.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=rng, majorDimension="ROWS")
        .execute()
    )
    values = resp.get("values", [])
    if not values:
        return []
    headers = [h.strip() for h in values[0]]
    rows = []
    for raw in values[1:]:
        row = {h: (raw[i].strip() if i < len(raw) else "") for i, h in enumerate(headers)}
        rows.append(row)
    if debug:
        print(f"[DEBUG] Read {len(rows)} rows from {tab_name}")
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# Build invoice data directly from BkdDts
# ──────────────────────────────────────────────────────────────────────────────


def build_invoice_data_from_bkddts(bkddts_rows, min_days_late, debug=False):
    """
    Build a map of venues → list of all open invoices (from BkdDts only).

    A venue qualifies for a statement if *any* invoice has age ≥ min_days_late.
    Once a venue qualifies, ALL invoices with a positive balance for that
    venue are included in the statement.

    Each invoice dict includes:
        docnbr, inv_date, amount, payments, balance, age, venue,
        first, email, attach, row_index
    """

    today = dt.date.today()
    venues = defaultdict(list)

    # Build invoice list from BkdDts
    for idx, r in enumerate(bkddts_rows):
        row_index = idx + 2  # header is row 1

        docnbr = r.get("Invoice Number", "").strip()
        if not docnbr:
            continue

        venue = (r.get("Performance Venue", "") or "").strip()
        if not venue:
            venue = "Unknown Venue"

        balance = safe_float(r.get("Invoice Balance Due", ""))
        # Only consider invoices with positive balance (unpaid)
        if balance <= 0:
            continue

        amount = safe_float(r.get("Price", ""))  # original invoice amount
        payments = max(amount - balance, 0.0)

        # Determine invoice date
        inv_date = date_from_invoice(docnbr)
        if inv_date is None:
            inv_date = parse_sheet_date(r.get("Performance Date", ""))

        age = (today - inv_date).days if inv_date else 0

        contact_email = (r.get("Contact Email", "") or "").strip()

        # Try to find a contact/first name if available; otherwise blank.
        first = (
            r.get("Contact Name", "")
            or r.get("Activity Director", "")
            or r.get("Contact", "")
            or ""
        ).strip()

        attach = (r.get("Attachment", "") or "").strip()

        invoice_info = dict(
            docnbr=docnbr,
            inv_date=inv_date,
            amount=round(amount, 2),
            payments=round(payments, 2),
            balance=round(balance, 2),
            age=age,
            venue=venue,
            first=first,
            email=contact_email,
            attach=attach,
            row_index=row_index,
        )

        venues[venue].append(invoice_info)

    # Filter venues based on min_days_late, but include all open invoices
    venue_map = {}
    for venue, invs in venues.items():
        if not invs:
            continue
        # A venue qualifies if any invoice age >= min_days_late
        if any(i["age"] >= min_days_late for i in invs):
            invs.sort(
                key=lambda r: (r["inv_date"] or dt.date(1970, 1, 1), r["docnbr"])
            )
            venue_map[venue] = invs

    if debug:
        print(
            f"[DEBUG] Venues with at least one invoice ≥ {min_days_late} days: {len(venue_map)}"
        )

    return venue_map


# ──────────────────────────────────────────────────────────────────────────────
# Drive helpers
# ──────────────────────────────────────────────────────────────────────────────


def extract_drive_file_id(url):
    m = re.search(r"/d/([a-zA-Z0-9_-]{20,})", url) or re.search(
        r"[?&]id=([a-zA-Z0-9_-]{20,})", url
    )
    return m.group(1) if m else None


def download_pdf(drive, link, dest_dir, debug=False):
    """
    Downloads a PDF from a Google Drive share link.
    Cleans up filenames and ensures the destination folder exists.
    Works for native PDF files as well as Google Docs exported as PDF.
    """
    fid = extract_drive_file_id(link)
    if not fid:
        if debug:
            print(f"[DEBUG] Could not parse Drive file ID from: {link}")
        return None

    try:
        meta = drive.files().get(fileId=fid, fields="name,mimeType").execute()
        name = meta.get("name", f"{fid}.pdf")

        # sanitize name to avoid slashes or illegal path chars
        safe_name = re.sub(r'[\\/:"*?<>|]+', "_", name)
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        outfile = dest_dir / safe_name
        outfile.parent.mkdir(parents=True, exist_ok=True)

        mime = meta.get("mimeType", "")
        if debug:
            print(f"[DEBUG] Downloading {safe_name} ({mime})")

        # Always try to fetch raw PDF binary — no export for these links
        request = drive.files().get_media(fileId=fid)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        with open(outfile, "wb") as f:
            f.write(fh.getvalue())

        if debug:
            print(f"[DEBUG] Saved: {outfile}")
        return outfile

    except HttpError as e:
        if debug:
            print(f"[DEBUG] Drive access failed for {fid}: {e}")
        return None
    except Exception as e:
        if debug:
            print(f"[DEBUG] PDF write failed for {fid}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Gmail helpers (HTML-only, refined branding)
# ──────────────────────────────────────────────────────────────────────────────


def build_html_email(venue, first, invs):
    total = sum(i["balance"] for i in invs)
    oldest = max(invs, key=lambda r: r["age"])
    intro = f"Hi {first or 'there'},"

    intro_paras = """
    <p>Thanks again for having <b>The Mixed Nuts</b> perform!</p>
    <p>Here's a summary of open invoices on your account.</p>
    """

    def build_invoice_table_html(invs):
        def fmt(d):
            return d.strftime("%Y-%m-%d") if d else ""

        rows = ""
        for r in invs:
            rows += f"""
            <tr>
              <td style="border:1px solid #999;padding:10px;">{r['docnbr']}</td>
              <td style="border:1px solid #999;padding:10px;">{fmt(r['inv_date'])}</td>
              <td style="border:1px solid #999;padding:10px;">${r['amount']:,.2f}</td>
              <td style="border:1px solid #999;padding:10px;">${r['payments']:,.2f}</td>
              <td style="border:1px solid #999;padding:10px;">${r['balance']:,.2f}</td>
              <td style="border:1px solid #999;padding:10px;">{r['age']} days</td>
            </tr>"""
        return f"""
        <table style="border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;font-size:13px;">
          <thead>
            <tr style="background:#eee;">
              <th style="border:1px solid #999;padding:10px;">Invoice #</th>
              <th style="border:1px solid #999;padding:10px;">Invoice Date</th>
              <th style="border:1px solid #999;padding:10px;">Amount</th>
              <th style="border:1px solid #999;padding:10px;">Payments</th>
              <th style="border:1px solid #999;padding:10px;">Balance</th>
              <th style="border:1px solid #999;padding:10px;">Age</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        """

    table = build_invoice_table_html(invs)
    summary = (
        f"<p>Total outstanding balance for <b>{venue}</b> = "
        f"<b>${total:,.2f}</b>.</p>"
    )

    oldest_line = (
        f"<p>The oldest invoice is <b>{oldest['docnbr']}</b> "
        f"at <b>{oldest['age']} days</b>.</p>"
    )

    attach_note = (
        "<p>We’ve attached copies of the invoice(s) for your convenience.</p>"
    )

    if oldest["age"] > 60:
        followup_extra = (
            "<p>Otherwise, could you let me know when the check(s) "
            "will be available?</p>"
        )
    else:
        followup_extra = ""

    followup_note = (
        "<p>Please let me know if you have any questions or if payment "
        "has already been processed.</p>" + followup_extra
    )

    sig = """
    <p>Thanks so much,<br>
    <b>Keith Day</b><br>
    The Mixed Nuts<br>
    <span style="font-size:smaller;color:#666666;margin-left:20px;">
      <i>A Legacy Performers production</i>
    </span><br>
    📞 385-377-0451</p>
    """

    return f"""
    <div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.45;color:#111;">
      <p>{intro}</p>
      {intro_paras}
      {table}
      {summary}
      {oldest_line}
      {attach_note}
      {followup_note}
      {sig}
    </div>
    """.strip()


def gmail_send_html(gmail, sender, to_addr, subject, html_body, attachments):
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"] = to_addr
    msg["From"] = sender
    msg["Subject"] = subject
    msg.add_alternative(html_body, subtype="html")
    for path in attachments:
        try:
            with open(path, "rb") as f:
                data = f.read()
            msg.add_attachment(
                data,
                maintype="application",
                subtype="pdf",
                filename=os.path.basename(path),
            )
        except Exception:
            pass
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser(
        description="Generate & send HTML collections statements (BkdDts-based)."
    )
    p.add_argument(
        "--sheet-id",
        required=True,
        help="Spreadsheet ID containing the BkdDts tab.",
    )
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()
    debug = a.debug

    mode = input("Send test emails or final emails? (T/F): ").strip().lower()
    test_mode = mode == "t"
    default_test = "keith.day@legacyperformers.org"
    if test_mode:
        entered = input(f"Enter test email address [{default_test}]: ").strip()
        test_to = entered or default_test
    else:
        test_to = None

    days = input("Enter minimum days late to include (default 31): ").strip()
    min_days = int(days) if days.isdigit() else 31

    try:
        sheets, drive, gmail = get_services(
            DEFAULT_CREDENTIALS_FILE, TOKEN_FILE, debug=debug
        )
    except Exception as e:
        print(
            f"Authentication failed.\nCreds: {DEFAULT_CREDENTIALS_FILE}\n"
            f"Token: {TOKEN_FILE}\nError: {e}"
        )
        sys.exit(1)

    # Read BkdDts only (balances already computed by formulas there)
    bkddts = read_sheet_as_dicts(sheets, a.sheet_id, "BkdDts", debug)

    data = build_invoice_data_from_bkddts(bkddts, min_days, debug)
    try:
        sender = (
            gmail.users().getProfile(userId="me").execute().get("emailAddress", "")
        )
    except Exception:
        sender = "me"

    venues_total = len(data)
    sent = 0

    for venue, invs in data.items():
        # Pick a row with an email if possible
        contact = next((i for i in invs if i["email"]), invs[0])
        recipient = test_to if test_mode else contact["email"]
        if not recipient:
            print(f"Skipping {venue} (no Contact Email).")
            continue

        html_body = build_html_email(venue, contact["first"], invs)
        subject = (
            "Friendly update on your Mixed Nuts performance invoices"
            if not test_mode
            else "[TEST] Friendly update on your Mixed Nuts performance invoices"
        )

        tmpdir = OUTPUT_DIR / f"_{re.sub('[^A-Za-z0-9]+', '_', venue)[:40]}"
        tmpdir.mkdir(exist_ok=True)
        attach_paths = []
        for r in invs:
            if r["attach"]:
                path = download_pdf(drive, r["attach"], tmpdir, debug)
                if path:
                    attach_paths.append(path)

        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        (OUTPUT_DIR / f"{stamp}_{re.sub('[^A-Za-z0-9]+', '_', venue)}.html").write_text(
            html_body, encoding="utf-8"
        )

        oldest_age = max(i["age"] for i in invs)
        print(f"\n{'=' * 60}")
        print(f"VENUE: {venue}")
        print(f"TO: {recipient}")
        print(f"Invoices: {len(invs)}  Total: ${sum(i['balance'] for i in invs):,.2f}")
        print(f"Oldest invoice: {oldest_age} days old")
        print(f"{'=' * 60}")

        if not prompt_yes_no("Send this email statement? (Y/N): "):
            continue

        try:
            gmail_send_html(gmail, sender, recipient, subject, html_body, attach_paths)
            sent += 1
            print("✅ Sent.")

            # ─────────────────────────────────────────────
            # Append note in BkdDts!AO for all related invoices (Final mode only)
            # ─────────────────────────────────────────────
            if not test_mode:
                today_note = f"{today_str()} Sent Collections Statement"
                bkddts_updates = []

                # For quick lookups, build a map of invoice number → index in bkddts list
                inv_to_index = {
                    row.get("Invoice Number", "").strip(): idx
                    for idx, row in enumerate(bkddts)
                    if row.get("Invoice Number", "").strip()
                }

                for inv in invs:
                    inv_num = inv["docnbr"]
                    if inv_num in inv_to_index:
                        idx = inv_to_index[inv_num]
                        row_idx = idx + 2  # sheet row number (header is row 1)

                        existing = bkddts[idx].get("Collection Notes", "").strip()
                        new_note = (
                            (existing + "\n" if existing else "") + today_note
                        )

                        # update cached data structure so we don't double-append
                        bkddts[idx]["Collection Notes"] = new_note

                        bkddts_updates.append(
                            {
                                "range": f"BkdDts!AO{row_idx}",
                                "values": [[new_note]],
                            }
                        )

                if bkddts_updates:
                    body = {"valueInputOption": "USER_ENTERED", "data": bkddts_updates}
                    try:
                        sheets.spreadsheets().values().batchUpdate(
                            spreadsheetId=a.sheet_id, body=body
                        ).execute()
                        if debug:
                            print(
                                f"[DEBUG] Updated Collection Notes for "
                                f"{len(bkddts_updates)} invoices."
                            )
                    except Exception as e:
                        print(f"[WARN] Could not update Collection Notes: {e}")

        except HttpError as e:
            print(f"❌ Gmail send failed: {e}")
        time.sleep(0.4)

    print(f"\nSummary: {sent}/{venues_total} venues emailed.")
    print(f"Output saved in: {OUTPUT_DIR.resolve()}")
    print("✅ Process complete.\n")


if __name__ == "__main__":
    main()
