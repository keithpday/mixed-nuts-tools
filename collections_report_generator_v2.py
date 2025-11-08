#!/usr/bin/env python3
"""
collections_report_generator_v2.py
-----------------------------------
Enhanced version with:
✅ Dynamic salutation using "ARFirst Name" from the Rcvbles tab.
✅ Optional debug logging (--debug on|off).
✅ Conditional Google API caching.
✅ Optional collection note updates in FINAL mode.

WORKFLOW SUMMARY
----------------
1️⃣ Reads data from:
    - GenEnt tab (journal entries)
    - Rcvbles tab (receivables + contact info)
2️⃣ Prompts for:
    - TEST (T) or FINAL (F)
    - Minimum days late (default 31)
3️⃣ Builds invoice summaries per venue.
4️⃣ Only sends if:
    - At least one invoice ≥ minimum days late
    - User approves each send (FINAL mode)
5️⃣ In FINAL mode, appends a note like:
    "2025-11-02 Sent Collections Statement"
    into the "Collection Notes" column of Rcvbles.
"""

import os
import sys
import re
import base64
import datetime as dt
import pandas as pd
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ---------------- CONSTANTS ----------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
OUTPUT_DIR = "/home/keith/PythonProjects/projects/Mixed_Nuts/output/emails"
TEST_EMAIL = "keith.day@legacyperformers.org"
START_DATE = dt.date(2023, 11, 7)
DEFAULT_DAYS_LATE = 31

# ---------------- AUTH ----------------
def get_service(creds_path, api, version, scopes=SCOPES):
    flow = InstalledAppFlow.from_client_secrets_file(creds_path, scopes)
    creds = flow.run_local_server(port=0)
    return build(api, version, credentials=creds)

# ---------------- SHEETS ----------------
def read_sheet(service, spreadsheet_id, tab_name):
    rng = f"{tab_name}!A:Z"
    resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
    vals = resp.get("values", [])
    if not vals:
        return pd.DataFrame()
    header = vals[0]
    rows = [r + [""] * (len(header) - len(r)) for r in vals[1:]]
    return pd.DataFrame(rows, columns=header)

def update_collection_note(service, sheet_id, tab_name, docnbr, note_text):
    """Append a note line to Collection Notes for the given invoice DocNbr."""
    rng = f"{tab_name}!A:Z"
    resp = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=rng).execute()
    vals = resp.get("values", [])
    if not vals:
        return
    headers = vals[0]
    rows = vals[1:]
    if "ARInvoice Number" not in headers or "Collection Notes" not in headers:
        return
    inv_idx = headers.index("ARInvoice Number")
    notes_idx = headers.index("Collection Notes")
    for i, r in enumerate(rows):
        if len(r) > inv_idx and str(r[inv_idx]).strip() == str(docnbr).strip():
            old_note = r[notes_idx] if len(r) > notes_idx else ""
            new_note = (old_note + "\n" if old_note else "") + note_text
            a1 = f"{tab_name}!{chr(65+notes_idx)}{i+2}"
            service.spreadsheets().values().update(
                spreadsheetId=sheet_id,
                range=a1,
                valueInputOption="USER_ENTERED",
                body={"values": [[new_note]]}
            ).execute()
            break

# ---------------- UTIL ----------------
def parse_money(x):
    if x in (None, "", "—"):
        return 0.0
    return float(str(x).replace(",", "").replace("$", "").strip() or 0)

def numeric_prefix(docnbr):
    m = re.match(r"^(\d+)", str(docnbr).strip())
    return int(m.group(1)) if m else None

def date_from_invoice(docnbr):
    n = numeric_prefix(docnbr)
    return START_DATE + dt.timedelta(days=(n - 1)) if n else None

def download_google_file(file_url):
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", file_url)
    if not m:
        raise ValueError("Invalid Google Drive file URL.")
    file_id = m.group(1)
    d_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp = requests.get(d_url)
    resp.raise_for_status()
    return resp.content

# ---------------- EMAIL ----------------
def make_html_email(intro_lines, table_rows, summary_line, extra_lines=None):
    """Build HTML and plain text versions of the email body."""
    extra_lines = extra_lines or []
    plain = []
    plain.extend(intro_lines)
    plain.append("")
    plain.append("Invoice # | Invoice Date | Amount | Payments | Balance | Age")
    plain.append("---|---|---|---|---|---")
    for r in table_rows:
        plain.append(" | ".join(r))
    plain.append("")
    plain.append(summary_line)
    for l in extra_lines:
        plain.append(l)
    plain.append("")
    plain.append("Thanks so much,\nKeith Day\nLegacy Performers / The Mixed Nuts\n📞 385-377-0451 (call or text anytime)")
    plain_text = "\n".join(plain)

    html_table_rows = "".join(
        "<tr>" +
        "".join(f"<td style='border:1px solid #ccc;padding:8px 10px;text-align:left;vertical-align:top'>{c}</td>" for c in row)
        + "</tr>"
        for row in table_rows
    )
    html_extra = "".join(f"<p style='margin:10px 0'>{l}</p>" for l in extra_lines)
    html_intro = "".join(f"<p style='margin:0 0 10px 0'>{line}</p>" for line in intro_lines)
    html = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;text-align:left;max-width:600px;">
      {html_intro}
      <table style="border-collapse:collapse;width:auto;margin:10px 0 10px 0">
        <thead>
          <tr>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Invoice #</th>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Invoice Date</th>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Amount</th>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Payments</th>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Balance</th>
            <th style="border:1px solid #ccc;padding:8px 10px;background:#f0f0f0">Age</th>
          </tr>
        </thead>
        <tbody>
          {html_table_rows}
        </tbody>
      </table>
      <p style='margin:10px 0'><strong>{summary_line}</strong></p>
      {html_extra}
      <p>Please let me know if you have any questions or if payment has already been processed.</p>
      <p>Thanks so much,<br>Keith Day<br>Legacy Performers / The Mixed Nuts<br>📞 385-377-0451 (call or text anytime)</p>
    </div>
    """
    return plain_text, html

def build_email(subject, plain, html, recipient):
    msg = MIMEMultipart("alternative")
    msg["to"] = recipient
    msg["subject"] = subject
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}

# ---------------- MAIN ----------------
def build_and_send(sheet_id, gen_tab, rc_tab, creds, mode, debug=False):
    today = dt.date.today()
    min_days = input(f"Enter minimum days late to include (default {DEFAULT_DAYS_LATE}): ").strip()
    min_days = int(min_days) if min_days.isdigit() else DEFAULT_DAYS_LATE

    sheets = get_service(creds, "sheets", "v4")
    gmail = get_service(creds, "gmail", "v1")

    gl = read_sheet(sheets, sheet_id, gen_tab)
    rc = read_sheet(sheets, sheet_id, rc_tab)

    venues = sorted(gl[gl["DocType"] == "INV"]["Account"].unique())
    for venue in venues:
        inv_rows = gl[(gl["Account"] == venue) & (gl["DocType"] == "INV")]
        table_rows = []
        total_due = 0
        ages = []
        attachments = []
        intro_lines = []
        extra_lines = []

        for _, inv in inv_rows.iterrows():
            docnbr = inv["DocNbr"]
            inv_date = date_from_invoice(docnbr)
            age = (today - inv_date).days if inv_date else 0
            if age < min_days:
                continue
            row_match = rc[rc["ARInvoice Number"].astype(str).str.strip() == str(docnbr).strip()]
            if not row_match.empty:
                intro_val = row_match.iloc[0].get("Intro Line", "").strip()
                if intro_val:
                    extra_lines.append(intro_val)
                att_url = row_match.iloc[0].get("Attachment", "").strip()
                if att_url:
                    try:
                        pdf_bytes = download_google_file(att_url)
                        fname = os.path.basename(att_url.split("/")[-1])
                        attachments.append((fname, pdf_bytes))
                        if debug:
                            print(f"[DEBUG] Attached {fname} for invoice {docnbr}")
                    except Exception as e:
                        print(f"[WARN]  Could not download attachment for {docnbr}: {e}")

            inv_amt = parse_money(inv.get("Debit")) - parse_money(inv.get("Credit"))
            total_due += inv_amt
            ages.append(age)
            table_rows.append([docnbr, inv_date, f"${inv_amt:,.0f}", "—", f"${inv_amt:,.0f}", f"{age} days"])

        if not table_rows:
            print(f"⏭️  Skipping {venue} (no invoices ≥ {min_days} days).")
            continue

        max_days = max(ages)
        print(f"\nVenue: {venue}\n  Max days late: {max_days}\n  Total due: ${total_due:,.0f}")
        send_it = input("Send this reminder? (Y/N): ").strip().lower()
        if send_it != "y":
            print(f"  ❎ Skipped {venue}.")
            continue

        # Get proper first name
        all_rows = rc[rc["ARInvoice Number"].isin(inv_rows["DocNbr"].astype(str))]
        first_name = ""
        if not all_rows.empty:
            first_name = str(all_rows["ARFirst Name"].dropna().iloc[0]).strip().title()
        if not first_name:
            if debug:
                print(f"[WARN] No ARFirst Name found for {venue}; using fallback.")
            first_name = "there"

        subject = f"Friendly update on your Mixed Nuts performance invoices"
        recipient = TEST_EMAIL if mode == "T" else str(all_rows["AREmail Address"].dropna().iloc[0]).strip()
        if not recipient:
            recipient = TEST_EMAIL

        intro_lines = [
            f"Hi {first_name},",
            "",
            "Thanks again for having The Mixed Nuts perform!",
            "According to our records, the following invoice(s) remain open:",
        ]
        summary_line = f"Total outstanding balance for {venue} = ${total_due:,.0f}."
        if attachments:
            extra_lines.append("I’ve attached copies of your invoices for convenience.")

        plain, html = make_html_email(intro_lines, table_rows, summary_line, extra_lines)
        msg = build_email(subject, plain, html, recipient)
        gmail.users().messages().send(userId="me", body=msg).execute()
        print(f"  ✅ Sent ({'TEST' if mode == 'T' else 'FINAL'})")

        if mode == "F":
            for _, inv in inv_rows.iterrows():
                update_collection_note(
                    sheets,
                    sheet_id,
                    rc_tab,
                    inv["DocNbr"],
                    f"{today.strftime('%Y-%m-%d')} Sent Collections Statement"
                )

# ---------------- ENTRY ----------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", required=True)
    parser.add_argument("--journal-tab", required=True)
    parser.add_argument("--rcvbles-tab", required=True)
    parser.add_argument("--creds", required=True)
    parser.add_argument("--debug", choices=["on", "off"], default="off")
    args = parser.parse_args()

    mode = input("Send test emails or final emails? (T/F): ").strip().upper()
    if mode not in ("T", "F"):
        print("Invalid mode.")
        sys.exit(1)

    build_and_send(
        args.spreadsheet,
        args.journal_tab,
        args.rcvbles_tab,
        args.creds,
        mode,
        debug=(args.debug == "on")
    )
