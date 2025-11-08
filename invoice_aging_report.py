#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invoice_aging_report.py — Reads the 'GenEnt' tab in your Google Sheet and
prints a text-based invoice aging report sorted by venue.

Supports double-entry format (Debit and Credit columns).
Invoice dates are derived from DocNbr numbers (base date 2023-11-07).
"""

import os
import re
import datetime as dt
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SPREADSHEET_ID = '1q9chtQNZnO5QcDBaYTjnV0sITxo7zAvTHfLT7MkZybs'   # ← Replace with your actual Sheet ID
RANGE_NAME = 'GenEnt!A:Z'
CREDENTIALS_FILE = '/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json'
TOKEN_FILE = 'invoice_aging_token.json'

# ──────────────────────────────────────────────────────────────
# Google Sheets auth
# ──────────────────────────────────────────────────────────────
def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('sheets', 'v4', credentials=creds)

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
BASE_DATE = dt.date(2023, 11, 7)

def parse_doc_date(docnbr):
    """Extract numeric portion from DocNbr and calculate invoice date."""
    m = re.search(r'\d+', str(docnbr))
    if not m:
        return None
    n = int(m.group(0))
    return BASE_DATE + dt.timedelta(days=n - 1)

# ──────────────────────────────────────────────────────────────
# Main processing
# ──────────────────────────────────────────────────────────────
def main():
    # Ask for minimum age
    try:
        min_age = input("Enter minimum age (days) of oldest invoice to include (default 31): ").strip()
        min_age = int(min_age) if min_age else 31
    except ValueError:
        min_age = 31
    print(f"→ Including venues with at least one invoice ≥ {min_age} days old.\n")

    # Google Sheets read
    service = get_service()
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    rows = result.get('values', [])

    if not rows:
        print("No data found in GenEnt.")
        return

    # Normalize row lengths
    max_len = len(rows[0])
    rows = [r + [''] * (max_len - len(r)) for r in rows]
    df = pd.DataFrame(rows[1:], columns=rows[0])

    # Identify Debit/Credit columns
    debit_col = next((c for c in df.columns if c.strip().lower() == 'debit'), None)
    credit_col = next((c for c in df.columns if c.strip().lower() == 'credit'), None)
    if not debit_col or not credit_col:
        print("❌ Could not find both 'Debit' and 'Credit' columns in the sheet.")
        print("Header row was:", df.columns.tolist())
        return

    # Compute signed amount
    df['Debit'] = pd.to_numeric(df[debit_col], errors='coerce').fillna(0.0)
    df['Credit'] = pd.to_numeric(df[credit_col], errors='coerce').fillna(0.0)
    df['Amount'] = df['Debit'] - df['Credit']

    # Clean key fields
    df['DocType'] = df['DocType'].astype(str).str.strip().str.upper()
    df['Account'] = df['Account'].astype(str).str.strip()
    df['DocNbr']  = df['DocNbr'].astype(str).str.strip()

    # Only accounting doctypes
    valid_doctypes = {'INV', 'PMT', 'DEP', 'CRN', 'ADJ', 'ACH'}
    df = df[df['DocType'].isin(valid_doctypes)]

    # Group and sum
    invoices = df.groupby(['Account', 'DocNbr', 'DocType']).agg({'Amount': 'sum'}).reset_index()

    inv_balances = []
    for (account, docnbr), group in invoices.groupby(['Account', 'DocNbr']):
        balance = group['Amount'].sum()
        if abs(balance) > 0.01:
            invoice_date = parse_doc_date(docnbr)
            if invoice_date:
                inv_balances.append({
                    'Account': account,
                    'DocNbr': docnbr,
                    'Date': invoice_date,
                    'Balance': balance
                })

    if not inv_balances:
        print("No outstanding balances.")
        return

    aging_df = pd.DataFrame(inv_balances)
    today = dt.date.today()
    aging_df['Days'] = (today - aging_df['Date']).apply(lambda d: d.days)
    aging_df.sort_values(['Account', 'Date'], inplace=True)

    # ─────────────── Print Text Report ───────────────
    print(f"\nINVOICE AGING REPORT — As of {today}\n")

    venue_count = 0
    for account, group in aging_df.groupby('Account'):
        # Include venue only if at least one invoice meets the min age
        if (group['Days'] >= min_age).any():
            venue_count += 1
            print(f"Account: {account}")
            print("------------------------------------------------------------")
            for _, row in group.iterrows():
                print(f"{row.DocNbr:<12} {row.Date}  {row.Days:>3} days     ${row.Balance:>9,.2f}")
            print("------------------------------------------------------------")
            print(f"Total for {account}: ${group['Balance'].sum():,.2f}\n")

    if venue_count == 0:
        print(f"No venues have invoices ≥ {min_age} days old.\n")
    else:
        print("Report complete.\n")

# ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    main()
