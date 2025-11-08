#!/usr/bin/env python3
"""
collections_report_generator.py
--------------------------------
Generates and emails collection statements for The Mixed Nuts.

Enhancements:
-------------
✅ Prompts for minimum days late (default 31).
✅ Skips venues unless at least one invoice meets or exceeds that age.
✅ Prompts before sending each email, showing venue, max days late, and total due.
✅ Includes any "Intro Line" text found in the Rcvbles tab (matching by unique Invoice Number).
✅ Attaches PDF invoice copies (from the "Attachment" column in the Rcvbles tab) for convenience.
✅ Table is left-aligned and fixed-width for readability.
✅ Only one Google authentication prompt per run.

How matching works:
-------------------
• The Journal tab (e.g., “GenEnt”) provides invoice and payment data.
• The Rcvbles tab provides contact info, Intro Lines, and invoice attachments.
• Invoices are matched using “DocNbr” in GenEnt == “ARInvoice Number” in Rcvbles.
  This is a perfect one-to-one mapping in this system.
"""

import os
import sys
import re
import base64
import datetime as dt
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io

# ---------------- CONSTANTS ----------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
OUTPUT_DIR = "/home/keith/PythonProjects/projects/Mixed_Nuts/output/emails"
TEST_EMAIL = "keith.day@legacyperformers.org"
START_DATE = dt.date(2023, 11, 7)

# ---------------- AUTH ----------------
def get_services(creds_path):
    """Authenticate once for Sheets, Drive, and Gmail."""
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    sheets = build("sheets", "v4", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    gmail = build("gmail", "v1", credentials=creds)
    return sheets, drive, gmail

# ---------------- HELPERS ----------------
def read_sheet(service, spreadsheet_id, tab_name):
    rng = f"{tab_name}!A:Z"
    resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
    values = resp.get("values", [])
    if not values:
        return pd.DataFrame()
    header = [h.strip() for h in values[0]]
    rows = [r + [""] * (len(header) - len(r)) for r in values[1:]]
    df = pd.DataFrame(rows, columns=header)
    return df

def parse_money(x):
    if not x:
        return 0.0
    s = str(x).replace("$", "").replace(",", "").strip()
    return float(s) if s else 0.0

def numeric_prefix(docnbr):
    m = re.match(r"^(\d+)", str(docnbr).strip())
    return int(m.group(1)) if m else None

def date_from_invoice(docnbr):
    n = numeric_prefix(docnbr)
    return START_DATE + dt.timedelta(days=(n - 1)) if n else None

def download_pdf_from_drive(drive, url_or_id):
    """Download file by ID (or extract ID from link)."""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url_or_id)
    file_id = m.group(1) if m else url_or_id
    try:
        meta = drive.files().get(fileId=file_id, fields="name").execute()
        name = meta["name"] + ".pdf" if not meta["name"].lower().endswith(".pdf") else meta["name"]
        buf = io.BytesIO()
        req = drive.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        buf.seek(0)
        return buf.read(), name
    except HttpError as e:
        print(f"  ⚠️  Could not download {url_or_id}: {e}")
        return None, None

def make_html_email(intro_lines, table_rows, summary_line, extra_lines):
    """Compose nicely formatted HTML + text email."""
    plain = []
    plain.extend(intro_lines)
    plain.append("")
    plain.append("Invoice # | Date | Amount | Payments | Balance | Age")
    plain.append("---|---|---|---|---|---")
    for r in table_rows:
        plain.append(" | ".join(r))
    plain.append("")
    plain.append(summary_line)
    for ln in extra_lines:
        plain.append(ln)
    plain.append("")
    plain.append("Thanks so much,\nKeith Day\nLegacy Performers / The Mixed Nuts\n📞 385-377-0451 (call or text anytime)")
    plain_text = "\n".join(plain)

    html_intro = "".join(f"<p style='margin:0 0 10px 0'>{line}</p>" for line in intro_lines)
    html_table_rows = "".join(
        "<tr>" +
        "".join(f"<td style='border:1px solid #ddd;padding:6px'>{cell}</td>" for cell in row)
        + "</tr>" for row in table_rows
    )
    html_extra = "".join(f"<p style='margin:10px 0'>{ln}</p>" for ln in extra_lines)

    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;text-align:left">
      {html_intro}
      <table style="border-collapse:collapse;margin:10px 0;text-align:left;width:auto;min-width:600px">
        <thead>
          <tr>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Invoice #</th>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Invoice Date</th>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Amount</th>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Payments</th>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Balance</th>
            <th style='border:1px solid #ddd;padding:6px;background:#f7f7f7'>Age</th>
          </tr>
        </thead>
        <tbody>{html_table_rows}</tbody>
      </table>
      <p><strong>{summary_line}</strong></p>
      {html_extra}
      <p style="margin:10px 0">Please let me know if you have any questions or if payment has already been processed.</p>
      <p style="margin:0">Thanks so much,<br>Keith Day<br>Legacy Performers / The Mixed Nuts<br>📞 385-377-0451 (call or text anytime)</p>
    </div>
    """
    return plain_text, html

def send_gmail(gmail, subject, plain_text, html_text, recipient, attachments):
    msg = MIMEMultipart("mixed")
    msg["to"] = recipient
    msg["subject"] = subject
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_text, "plain"))
    alt.attach(MIMEText(html_text, "html"))
    msg.attach(alt)
    for data, fname in attachments:
        part = MIMEBase("application", "pdf")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
        msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()

# ---------------- MAIN ----------------
def build_and_send(spreadsheet_id, journal_tab, rcvbles_tab, creds_path, mode):
    sheets, drive, gmail = get_services(creds_path)
    today = dt.date.today()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    gl = read_sheet(sheets, spreadsheet_id, journal_tab)
    rc = read_sheet(sheets, spreadsheet_id, rcvbles_tab)

    # Normalize header spacing
    gl.columns = [c.strip() for c in gl.columns]
    rc.columns = [c.strip() for c in rc.columns]

    invs = gl[gl["DocType"] == "INV"].copy()
    pmts = gl[gl["DocType"].isin(["PMT", "ACH", "DEP", "ADJ", "CRN"])].copy()

    min_days = input("Enter minimum days late to include (default 31): ").strip()
    min_days = int(min_days or 31)

    venues = sorted(invs["Account"].apply(lambda a: a[7:].strip() if str(a).lower().startswith("rcvbls ") else str(a)).unique())

    for venue in venues:
        inv_rows = invs[invs["Account"].str.contains(venue, case=False, na=False)]
        payments = pmts[pmts["Account"].str.contains(venue, case=False, na=False)]
        if inv_rows.empty:
            continue

        table_rows = []
        total_due = 0
        max_days = 0
        attachments = []
        intro_lines = []

        for _, inv in inv_rows.iterrows():
            docnbr = str(inv["DocNbr"]).strip()
            amt = parse_money(inv["Debit"]) - parse_money(inv["Credit"])
            if amt <= 0:
                continue
            inv_date = date_from_invoice(docnbr)
            bal = amt
            subset = payments[payments["DocNbr"] == docnbr]
            for _, p in subset.iterrows():
                bal -= max(0, parse_money(p["Credit"]) - parse_money(p["Debit"]))
            if bal <= 0:
                continue

            age = (today - inv_date).days if inv_date else 0
            max_days = max(max_days, age)
            total_due += bal
            table_rows.append([
                docnbr,
                inv_date.strftime("%Y-%m-%d") if inv_date else "—",
                f"${round(amt):,}",
                "—",
                f"${round(bal):,}",
                f"{age} days"
            ])

            # Pull matching Rcvbles row for Intro Line & attachment
            match = rc[rc["ARInvoice Number"].astype(str).str.strip() == docnbr]
            if not match.empty:
                intro_line = str(match.iloc[0].get("Intro Line", "")).strip()
                if intro_line:
                    intro_lines.append(intro_line)
                    print(f"  [DEBUG] Intro Line for {venue}/{docnbr}: {intro_line}")
                att_link = str(match.iloc[0].get("Attachment", "")).strip()
                if att_link:
                    data, fname = download_pdf_from_drive(drive, att_link)
                    if data:
                        attachments.append((data, fname))
                        print(f"  [DEBUG] Attached {fname} for {venue}/{docnbr}")
            else:
                print(f"  [DEBUG] No Rcvbles match for invoice {docnbr}")

        if not table_rows or max_days < min_days:
            print(f"⏭️  Skipping {venue} (max {max_days} days < {min_days})")
            continue

        print(f"\nVenue: {venue}\n  Max days late: {max_days}\n  Total due: ${round(total_due):,}")
        send_it = input("Send this reminder? (Y/N): ").strip().lower()
        if send_it != "y":
            print(f"  ❎ Skipped {venue}.")
            continue

        subject_prefix = "[TEST] " if mode == "T" else ""
        subject = f"{subject_prefix}Friendly update on your Mixed Nuts performance invoices"
        summary_line = f"Total outstanding balance for {venue} = ${round(total_due):,}."
        if intro_lines:
            intro_lines.append("I’ve attached copies of the invoices for your convenience. (You may already have these on file.)")

        plain, html = make_html_email(
            [f"Hi there,", "", "Thanks again for having The Mixed Nuts perform!"],
            table_rows,
            summary_line,
            intro_lines
        )

        recipient = TEST_EMAIL
        try:
            send_gmail(gmail, subject, plain, html, recipient, attachments)
            mode_label = "TEST" if mode == "T" else "FINAL"
            print(f"  ✅ Sent ({mode_label})")
        except Exception as e:
            print(f"  ❌ Failed to send {venue}: {e}")

    print(f"\nAll done in {'TEST' if mode == 'T' else 'FINAL'} mode!")

# ---------------- ENTRY ----------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", required=True)
    parser.add_argument("--journal-tab", required=True)
    parser.add_argument("--rcvbles-tab", required=True)
    parser.add_argument("--creds", required=True)
    args = parser.parse_args()

    mode = input("Send test emails or final emails? (T/F): ").strip().upper() or "T"
    build_and_send(args.spreadsheet, args.journal_tab, args.rcvbles_tab, args.creds, mode)
