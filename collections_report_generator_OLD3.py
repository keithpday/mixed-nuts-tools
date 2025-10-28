#!/usr/bin/env python3
"""
collections_report_generator.py
--------------------------------
Generates and emails collection statements for The Mixed Nuts.

Workflow:
1) Prompt for Test (T) or Final (F) mode (case-insensitive).
2) Generate draft emails from GenEnt + Rcvbles.
3) Send via Gmail API:
   - TEST: all to keith.day@legacyperformers.org, subject prefixed with [TEST]
   - FINAL: to real recipients (AREmail Address). CONFIRMATION REQUIRED.

Args:
  --spreadsheet <Google Sheet ID>
  --journal-tab <Journal tab name> (e.g., GenEnt)
  --rcvbles-tab <Receivables tab name> (e.g., Rcvbles)
  --creds <path to credentials.json>
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
    """Authorize and build a Google API service."""
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    return build(api, version, credentials=creds)

# ------------------ SHEETS HELPERS ------------------
def read_sheet_values(service, spreadsheet_id: str, tab_name: str) -> pd.DataFrame:
    """Read tab into DataFrame with normalized rows."""
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
    """Build an HTML email body with styled table; return (plain_text, html_text)."""
    # Plain text (fallback / saved as .txt)
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

    # HTML version
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
    """Create MIME multipart/alternative message for Gmail API."""
    msg = MIMEMultipart("alternative")
    msg["to"] = recipient
    msg["subject"] = subject
    msg.attach(MIMEText(plain_text, "plain"))
    msg.attach(MIMEText(html_text, "html"))
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}

def send_gmail(gmail_service, subject, plain_text, html_text, recipient):
    """Send email via Gmail API."""
    body = build_multipart_email(subject, plain_text, html_text, recipient)
    gmail_service.users().messages().send(userId="me", body=body).execute()

# ------------------ MAIN COLLECTION BUILDER ------------------
def build_and_send(spreadsheet_id, journal_tab, rcvbles_tab, creds_path, mode):
    today = dt.date.today()

    sheets_service = get_service(creds_path, "sheets", "v4")
    gmail_service = get_service(creds_path, "gmail", "v1")

    # Load data
    gl = read_sheet_values(sheets_service, spreadsheet_id, journal_tab)
    rc = read_sheet_values(sheets_service, spreadsheet_id, rcvbles_tab)
    if gl.empty or rc.empty:
        print("Error: Could not read data from sheets.")
        sys.exit(1)

    # Ensure expected columns exist
    for col in ["Seq","Date","Description","Account","Debit","Credit","DocType","DocNbr","ExtDoc"]:
        if col not in gl.columns:
            gl[col] = ""
    for col in ["ARVenue","ARContact","ARFirst Name","ARCellPhone","ARWorkPhone","AREmail Address"]:
        if col not in rc.columns:
            rc[col] = ""

    # Filter invoices & payments
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

        # Contact info
        contact = rc[rc["ARVenue"].astype(str).str.strip().str.lower() == venue.strip().lower()]
        first_name = ""
        if not contact.empty:
            first_name = str(contact.get("ARFirst Name", "").iloc[0]).strip().title()
            if not first_name:
                first_name = str(contact.get("ARContact", "").iloc[0]).strip().split()[0].title()
        first_name = first_name or "there"

        recipient_real = (
            contact["AREmail Address"].iloc[0].strip()
            if not contact.empty and "AREmail Address" in contact
            else ""
        )
        recipient = TEST_EMAIL if mode == "T" else (recipient_real or TEST_EMAIL)

        # Build invoice rows
        table_rows = []
        total_due = 0
        for _, inv in inv_rows.iterrows():
            inv_num = inv.get("DocNbr", "")
            inv_amt = parse_money(inv.get("Debit", 0)) - parse_money(inv.get("Credit", 0))
            if inv_amt <= 0:
                continue
            inv_date = date_from_invoice(inv_num)
            bal = inv_amt
            pay_lines = []
            subset = payments[payments["DocNbr"] == inv_num]
            for _, p in subset.iterrows():
                credit = parse_money(p.get("Credit", 0))
                debit = parse_money(p.get("Debit", 0))
                applied = credit - debit
                if applied > 0:
                    p_date = p.get("Date", "")
                    p_ref = str(p.get("ExtDoc", "")).strip()
                    pay_lines.append(f"{p_date} · {p_ref} · ${round(applied):,}" if p_ref else f"{p_date} · ${round(applied):,}")
                    bal -= applied
            if bal <= 0:
                continue
            total_due += max(0, bal)
            age = (today - inv_date).days if inv_date else ""
            overdue = "60+ days" if (isinstance(age, int) and age >= 60) else ("30+ days" if (isinstance(age, int) and age >= 30) else "")
            payments_text = "; ".join(pay_lines) if pay_lines else "—"
            table_rows.append([
                str(inv_num),
                inv_date.strftime("%Y-%m-%d") if inv_date else "—",
                f"${round(inv_amt):,}",
                payments_text,
                f"${round(max(0, bal)):,}",
                f"{age} days {'(' + overdue + ')' if overdue else ''}".strip()
            ])

        if not table_rows:
            continue

        subject = "Friendly update on your Mixed Nuts performance invoices"
        if mode == "T":
            subject = "[TEST] " + subject

        intro_lines = [
            f"Hi {(first_name or 'there')},",
            "",
            "Thanks again for having The Mixed Nuts perform!",
            "According to our records, the following invoice(s) remain open. Could you please review and confirm payment status?",
        ]
        summary_line = f"Total outstanding balance for {venue} = ${round(total_due):,}."
        plain_text, html_text = make_html_email(intro_lines, table_rows, summary_line)

        filename = os.path.join(OUTPUT_DIR, f"{re.sub(r'[^A-Za-z0-9_.-]+','_', venue)}.txt")
        with open(filename, "w", encoding="utf-8") as f:
            f.write(plain_text)

        all_emails.append({
            "Subject": subject,
            "Body": plain_text,
            "Recipients": recipient,
            "Venue": venue,
            "_html": html_text,
            "_rows": table_rows,
            "_total": total_due,
        })

    # Confirm before sending FINAL
    if mode == "F":
        confirm = input("Are you sure you want to send FINAL emails to real recipients? (Y/N): ").strip().lower()
        if confirm != "y":
            print("Final send canceled. Exiting without sending.")
            return

    # Send loop
    for e in all_emails:
        subj, recipient, venue = e["Subject"], e["Recipients"], e["Venue"]
        plain_text = e["Body"]
        html_text = e["_html"]

        # In FINAL mode — show oldest invoice and total, ask permission
        if mode == "F":
            rows = e.get("_rows", [])
            total_due = e.get("_total", 0)
            oldest_date = None
            oldest_num = None
            for r in rows:
                try:
                    inv_date = dt.datetime.strptime(r[1], "%Y-%m-%d").date()
                except Exception:
                    continue
                if not oldest_date or inv_date < oldest_date:
                    oldest_date = inv_date
                    oldest_num = r[0]
            age = (today - oldest_date).days if oldest_date else None

            print(f"\nVenue: {venue}")
            if oldest_date:
                print(f"Oldest invoice: {oldest_num} ({oldest_date}) – {age} days old")
            else:
                print("Oldest invoice date could not be determined.")
            print(f"Total outstanding: ${round(total_due):,}")

            send_it = input("Send this reminder? (Y/N): ").strip().lower()
            if send_it != "y":
                print(f"  ❎ Skipped {venue}.")
                continue

        print(f"Sending to {venue} ({recipient})...")
        try:
            send_gmail(gmail_service, subj, plain_text, html_text, recipient)
            e["Sent?"] = f"Sent {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} ({'TEST' if mode == 'T' else 'FINAL'})"
            print("  ✅ OK")
        except Exception as ex:
            e["Sent?"] = f"FAILED: {ex}"
            print(f"  ❌ FAILED: {ex}")
        sent_rows.append(e)

    # Final summary
    if mode == "F":
        sent_final = sum(1 for e in sent_rows if e["Sent?"].startswith("Sent"))
        skipped_final = len(all_emails) - sent_final
        print(f"\nSummary: {sent_final} emails sent, {skipped_final} skipped.")

    print(f"All done in {'TEST' if mode == 'T' else 'FINAL'} mode!")


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
        mode = mode.lower()
        if mode == "t":
            mode = "T"
        elif mode == "f":
            mode = "F"
        else:
            print("Invalid selection. Exiting.")
            sys.exit(1)

    build_and_send(args.spreadsheet, args.journal_tab, args.rcvbles_tab, args.creds, mode)
