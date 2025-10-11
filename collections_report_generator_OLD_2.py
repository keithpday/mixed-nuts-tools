#!/usr/bin/env python3
"""
collections_report_generator.py
--------------------------------
Generates and optionally emails collection statements for The Mixed Nuts.

Workflow:
1. Prompts for Test (T) or Final (F) mode.
2. Deletes any EmailDrafts rows with today's date.
3. Generates new collection report emails from GenEnt + Rcvbles tabs.
4. Writes them to EmailDrafts and /output/emails/.
5. Sends via Gmail API to either test or real recipients.

Args:
  --spreadsheet  <Google Sheet ID>
  --journal-tab  <Journal tab name> (e.g., GenEnt)
  --rcvbles-tab  <Receivables tab name> (e.g., Rcvbles)
  --emaildrafts-tab <EmailDrafts tab name>
  --creds  <path to credentials.json>

Author: Legacy Performers / The Mixed Nuts
"""

import os
import sys
import pandas as pd
import datetime as dt
from email.mime.text import MIMEText
import base64
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ------------------ CONSTANTS ------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

OUTPUT_DIR = "/home/keith/PythonProjects/projects/Mixed_Nuts/output/emails"
TEST_EMAIL = "keith.day@legacyperformers.org"

# ------------------ HELPERS ------------------
def get_service(creds_path, api, version):
    """Authorize and build a Google API service."""
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
    creds = flow.run_local_server(port=0)
    return build(api, version, credentials=creds)

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

def clear_todays_drafts(service, spreadsheet_id, tab_name, today_str):
    """Remove all rows from EmailDrafts that match today's date."""
    print(f"Wiping EmailDrafts rows for {today_str}...")
    df = read_sheet_values(service, spreadsheet_id, tab_name)
    if df.empty:
        return
    keep = df[df["Date"] != today_str]
    body = {"values": [keep.columns.tolist()] + keep.values.tolist()}
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id, range=f"{tab_name}!A:Z"
    ).execute()
    if not keep.empty:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{tab_name}!A1",
            valueInputOption="RAW",
            body=body,
        ).execute()

def date_from_invoice(inv_num: str):
    """Derive date from invoice number."""
    try:
        num = int("".join([c for c in inv_num if c.isdigit()]))
        base = dt.date(2023, 11, 7)
        return base + dt.timedelta(days=(num - 1))
    except:
        return None

def build_email(subject, body, recipient):
    """Create MIME message for Gmail API."""
    message = MIMEText(body, "plain")
    message["to"] = recipient
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}

def send_gmail(service, subject, body, recipient):
    """Send an email via Gmail API."""
    msg = build_email(subject, body, recipient)
    service.users().messages().send(userId="me", body=msg).execute()

def write_emails_to_sheet(service, spreadsheet_id, tab_name, emails_df):
    """Append generated emails to EmailDrafts tab."""
    body = {"values": [emails_df.columns.tolist()] + emails_df.values.tolist()}
    service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=f"{tab_name}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()

# ------------------ MAIN COLLECTION BUILDER ------------------
def build_and_send(spreadsheet_id, journal_tab, rcvbles_tab, email_tab, creds_path, mode):
    today = dt.date.today()
    today_str = today.strftime("%Y-%m-%d")

    sheets_service = get_service(creds_path, "sheets", "v4")
    gmail_service = get_service(creds_path, "gmail", "v1")

    # Clean old drafts
    clear_todays_drafts(sheets_service, spreadsheet_id, email_tab, today_str)

    # Load data
    gl = read_sheet_values(sheets_service, spreadsheet_id, journal_tab)
    rc = read_sheet_values(sheets_service, spreadsheet_id, rcvbles_tab)
    if gl.empty or rc.empty:
        print("Error: Could not read data from sheets.")
        sys.exit(1)

    # Filter invoices & payments
    invs = gl[gl["DocType"] == "INV"].copy()
    pmts = gl[gl["DocType"].isin(["PMT", "ACH", "DEP", "ADJ", "CRN"])].copy()

    # Build email drafts
    all_emails = []
    venues = invs["Account"].unique()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for venue in venues:
        inv_rows = invs[invs["Account"] == venue]
        payments = pmts[pmts["Account"] == venue]

        if inv_rows.empty:
            continue

        # Merge with receivables for contact info
        contact = rc[rc["ARVenue"].str.lower() == venue.lower()]
        first_name = contact["ARFirst Name"].values[0] if not contact.empty else ""
        recipient = TEST_EMAIL if mode == "T" else contact["AREmail Address"].values[0] if "AREmail Address" in contact else TEST_EMAIL
        phone = contact["ARCellPhone"].values[0] if not contact.empty else ""
        work = contact["ARWorkPhone"].values[0] if not contact.empty else ""

        rows_txt = []
        total_due = 0
        for _, inv in inv_rows.iterrows():
            inv_num = inv.get("DocNbr", "")
            amt = float(inv.get("Debit", "0") or 0)
            inv_date = date_from_invoice(inv_num)
            balance = amt
            pay_lines = []
            for _, p in payments.iterrows():
                if p.get("DocNbr") == inv_num:
                    p_amt = float(p.get("Credit", "0") or 0)
                    p_date = p.get("Date", "")
                    p_ext = p.get("ExtDoc", "")
                    pay_lines.append(f"{p_date} {p_ext} ${p_amt:,.0f}")
                    balance -= p_amt
            if balance <= 0:
                continue  # Skip fully paid invoices
            total_due += balance
            age = (today - inv_date).days if inv_date else ""
            flag = ""
            if age and age >= 60:
                flag = "⚠️ 60+ days"
            elif age and age >= 30:
                flag = "30+ days"
            pay_text = "; ".join(pay_lines) if pay_lines else ""
            rows_txt.append(
                f"{inv_num}\t{inv_date}\t${amt:,.0f}\t{pay_text or '—'}\t${balance:,.0f}\t{age} days {flag}"
            )

        if not rows_txt:
            continue

        # Build message
        subj = f"Friendly update on your Mixed Nuts performance invoices"
        if mode == "T":
            subj = "[TEST] " + subj

        intro = f"Hi {first_name},\n\nThanks again for having The Mixed Nuts perform!"
        intro += "\nAccording to our records, the following invoice(s) remain open.\nCould you please review and confirm payment status?\n"
        table = "\n\nInvoice# | Date | Amount | Payments | Balance | Age\n" + "\n".join(rows_txt)
        summary = f"\n\nTotal outstanding balance for {venue} = ${total_due:,.0f}."
        body = f"{intro}{table}{summary}\n\nThanks so much,\nKeith Day\nLegacy Performers / The Mixed Nuts\n📞 385-377-0451 (call or text anytime)"
        if phone:
            body += f"\nContact: {first_name} ({phone} {work})"

        # Save locally
        filename = os.path.join(OUTPUT_DIR, f"{venue.replace(' ', '_')}.txt")
        with open(filename, "w") as f:
            f.write(body)

        all_emails.append({
            "Date": today_str,
            "Subject": subj,
            "Body": body,
            "Comments": f"Generated in {'TEST' if mode == 'T' else 'FINAL'} mode",
            "Recipients": recipient,
            "Sent?": "",
            "Venue": venue,
        })

    # Write to sheet
    emails_df = pd.DataFrame(all_emails)
    write_emails_to_sheet(sheets_service, spreadsheet_id, email_tab, emails_df)
    print(f"Wrote {len(emails_df)} rows to EmailDrafts.")
    print(f"Wrote {len(emails_df)} .txt files to {OUTPUT_DIR}")

    # Send emails
    for _, e in emails_df.iterrows():
        subj, body, recip, venue = e["Subject"], e["Body"], e["Recipients"], e["Venue"]
        print(f"Sending to {venue} ({recip})...")
        try:
            send_gmail(gmail_service, subj, body, recip)
            e["Sent?"] = f"Sent {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} ({'TEST' if mode == 'T' else 'FINAL'})"
            print("  ✅ OK")
        except Exception as ex:
            e["Sent?"] = f"FAILED: {ex}"
            print(f"  ❌ FAILED: {ex}")

    # Update Sent? column
    body = {"values": [emails_df.columns.tolist()] + emails_df.values.tolist()}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{email_tab}!A1",
        valueInputOption="RAW",
        body=body,
    ).execute()
    print(f"All done in {'TEST' if mode == 'T' else 'FINAL'} mode!")

# ------------------ ENTRY ------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", required=True)
    parser.add_argument("--journal-tab", required=True)
    parser.add_argument("--rcvbles-tab", required=True)
    parser.add_argument("--emaildrafts-tab", required=True)
    parser.add_argument("--creds", required=True)
    args = parser.parse_args()

    mode = input("Send test emails or final emails? (T/F): ").strip().upper()
    if mode not in ("T", "F"):
        print("Invalid selection. Exiting.")
        sys.exit(1)

    build_and_send(args.spreadsheet, args.journal_tab, args.rcvbles_tab, args.emaildrafts_tab, args.creds, mode)
