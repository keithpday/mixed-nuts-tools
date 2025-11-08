#!/usr/bin/env python3
"""
collections_report_generator.py
--------------------------------
Generates and emails collection statements for The Mixed Nuts.

New in this version:
- Prompts for a minimum number of days late before processing.
- Skips venues with no invoices older than that threshold.
- Prompts before sending each qualifying email (showing venue, max age, and total due).
"""

import os
import sys
import re
import pandas as pd
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ------------------ CONSTANTS ------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

OUTPUT_DIR = "/home/keith/PythonProjects/projects/Mixed_Nuts/output/emails"
TEST_EMAIL = "keith.day@legacyperformers.org"
START_DATE = dt.date(2023, 11, 7)  # invoice #1 base date

# ------------------ AUTH ------------------
def get_service(creds_path, api, version):
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    return build(api, version, credentials=creds)

# ------------------ SHEETS HELPERS ------------------
def read_sheet_values(service, spreadsheet_id: str, tab_name: str) -> pd.DataFrame:
    rng = f"{tab_name}!A:Z"
    resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
    values = resp.get("values", [])
    if not values:
        return pd.DataFrame()
    header = values[0]
    rows = values[1:]
    ncols = len(header)
    normalized = [r + [""] * (ncols - len(r)) if len(r) < ncols else r[:ncols] for r in rows]
    return pd.DataFrame(normalized, columns=header)

# ------------------ AR LOGIC ------------------
def parse_money(x):
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("$", "")
    return float(s) if s else 0.0

def numeric_prefix(docnbr: str):
    if not isinstance(docnbr, str):
        docnbr = "" if pd.isna(docnbr) else str(docnbr)
    m = re.match(r"^(\d+)", docnbr.strip())
    return int(m.group(1)) if m else None

def date_from_invoice(docnbr: str):
    n = numeric_prefix(docnbr)
    if n is None:
        return None
    return START_DATE + dt.timedelta(days=(n - 1))

def normalize_venue_from_account(account: str) -> str:
    if not isinstance(account, str):
        return ""
    a = account.strip()
    return a[7:].strip() if a.lower().startswith("rcvbls ") else a

# ------------------ EMAIL BUILD/SEND ------------------
def make_html_email(intro_lines, table_rows, summary_line):
    plain = []
    plain.extend(intro_lines)
    plain.append("")
    plain.append("Invoice # | Invoice Date | Amount | Payments | Balance | Age")
    plain.append("---|---|---|---|---|---")
    for r in table_rows:
        plain.append(" | ".join(r))
    plain.append("")
    plain.append(summary_line)
    plain.append("")
    plain.append("Thanks so much,")
    plain.append("Keith Day")
    plain.append("Legacy Performers / The Mixed Nuts")
    plain.append("📞 385-377-0451 (call or text anytime)")
    plain_text = "\n".join(plain)

    html_intro = "".join(f"<p style='margin:0 0 10px 0'>{line}</p>" for line in intro_lines)
    html_table_rows = "".join(
        "<tr>" +
        "".join(f"<td style='border:1px solid #ddd;padding:6px;vertical-align:top'>{cell}</td>" for cell in row)
        + "</tr>"
        for row in table_rows
    )
    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.4;color:#222">
      {html_intro}
      <table style="border-collapse:collapse;width:100%;margin:10px 0">
        <thead>
          <tr>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Invoice #</th>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Invoice Date</th>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Amount</th>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Payments</th>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Balance</th>
            <th style="text-align:left;border:1px solid #ddd;padding:6px;background:#f7f7f7">Age</th>
          </tr>
        </thead>
        <tbody>
          {html_table_rows}
        </tbody>
      </table>
      <p style="margin:10px 0"><strong>{summary_line}</strong></p>
      <p style="margin:10px 0">Please let me know if you have any questions or if payment has already been processed.</p>
      <p style="margin:0">Thanks so much,<br>
      Keith Day<br>
      Legacy Performers / The Mixed Nuts<br>
      📞 385-377-0451 (call or text anytime)</p>
    </div>
    """
    return plain_text, html

def build_multipart_email(subject, plain_text, html_text, recipient):
    msg = MIMEMultipart("alternative")
    msg["to"] = recipient
    msg["subject"] = subject
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_text, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}

def send_gmail(gmail_service, subject, plain_text, html_text, recipient):
    body = build_multipart_email(subject, plain_text, html_text, recipient)
    gmail_service.users().messages().send(userId="me", body=body).execute()

# ------------------ MAIN COLLECTION BUILDER ------------------
def build_and_send(spreadsheet_id, journal_tab, rcvbles_tab, creds_path, mode):
    today = dt.date.today()

    # Prompt for minimum days late
    try:
        min_days_late = int(input("Enter minimum days late to include (e.g., 30): ").strip())
    except ValueError:
        print("Invalid input. Defaulting to 30 days.")
        min_days_late = 30

    sheets_service = get_service(creds_path, "sheets", "v4")
    gmail_service = get_service(creds_path, "gmail", "v1")

    gl = read_sheet_values(sheets_service, spreadsheet_id, journal_tab)
    rc = read_sheet_values(sheets_service, spreadsheet_id, rcvbles_tab)
    if gl.empty or rc.empty:
        print("Error: Could not read data from sheets.")
        sys.exit(1)

    for col in ["Seq","Date","Description","Account","Debit","Credit","DocType","DocNbr","ExtDoc"]:
        if col not in gl.columns:
            gl[col] = ""
    for col in ["ARInvoice Number","ARVenue","ARContact","ARFirst Name","AREmail Address"]:
        if col not in rc.columns:
            rc[col] = ""

    invs = gl[gl["DocType"] == "INV"].copy()
    pmts = gl[gl["DocType"].isin(["PMT", "ACH", "DEP", "ADJ", "CRN"])].copy()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    invs["Venue"] = invs["Account"].map(normalize_venue_from_account)
    pmts["Venue"] = pmts["Account"].map(normalize_venue_from_account)
    venues = sorted(invs["Venue"].dropna().unique())

    all_emails = []
    sent_rows = []

    for venue in venues:
        inv_rows = invs[invs["Venue"] == venue].copy()
        payments = pmts[pmts["Venue"] == venue].copy()

        table_rows = []
        total_due = 0
        max_age = 0

        for _, inv in inv_rows.iterrows():
            inv_num = inv.get("DocNbr", "")
            inv_amt = parse_money(inv.get("Debit", 0)) - parse_money(inv.get("Credit", 0))
            if inv_amt <= 0:
                continue
            inv_date = date_from_invoice(inv_num)
            bal = inv_amt
            subset = payments[payments["DocNbr"] == inv_num]
            for _, p in subset.iterrows():
                credit = parse_money(p.get("Credit", 0))
                debit = parse_money(p.get("Debit", 0))
                applied = credit - debit
                if applied > 0:
                    bal -= applied
            if bal <= 0:
                continue
            total_due += max(0, bal)
            age = (today - inv_date).days if inv_date else 0
            max_age = max(max_age, age)
            overdue = "60+ days" if age >= 60 else ("30+ days" if age >= 30 else "")
            table_rows.append([
                str(inv_num),
                inv_date.strftime("%Y-%m-%d") if inv_date else "—",
                f"${round(inv_amt):,}",
                "—",
                f"${round(max(0, bal)):,}",
                f"{age} days {'(' + overdue + ')' if overdue else ''}".strip()
            ])

        # Skip if no invoices or all under threshold
        if not table_rows or max_age < min_days_late:
            continue

        print(f"\nVenue: {venue}")
        print(f"Max days late: {max_age}")
        print(f"Total outstanding: ${round(total_due):,}")
        confirm_send = input("Send this collections email? (y/N): ").strip().lower()
        if confirm_send != "y":
            print("  ❎ Skipped.")
            continue

        # Build and send
        subject = "Friendly update on your Mixed Nuts performance invoices"
        if mode == "T":
            subject = "[TEST] " + subject
        intro_lines = [
            f"Hi there,",
            "",
            "Thanks again for having The Mixed Nuts perform!",
            "According to our records, the following invoice(s) remain open. Could you please review and confirm payment status?",
        ]
        summary_line = f"Total outstanding balance for {venue} = ${round(total_due):,}."
        plain_text, html_text = make_html_email(intro_lines, table_rows, summary_line)
        recipient = TEST_EMAIL if mode == "T" else TEST_EMAIL  # (You can re-enable real emails later)

        print(f"Sending to {venue} ({recipient})...")
        try:
            send_gmail(gmail_service, subject, plain_text, html_text, recipient)
            print("  ✅ OK")
        except Exception as ex:
            print(f"  ❌ FAILED: {ex}")

    print("\nAll done!")

# ------------------ ENTRY ------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", required=True)
    parser.add_argument("--journal-tab", required=True)
    parser.add_argument("--rcvbles-tab", required=True)
    parser.add_argument("--creds", required=True)
    args = parser.parse_args()

    mode = input("Send test emails or final emails? (T/F): ").strip().upper()
    if mode not in ("T", "F"):
        print("Invalid selection. Exiting.")
        sys.exit(1)

    build_and_send(args.spreadsheet, args.journal_tab, args.rcvbles_tab, args.creds, mode)
