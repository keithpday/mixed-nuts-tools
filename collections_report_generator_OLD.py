import argparse
import os
import re
from datetime import datetime, date, timedelta
import pandas as pd

# Google API
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

DEFAULT_CREDS_DIR = os.path.join(os.path.expanduser("~"), ".config", "mixed_nuts_gsheets")
DEFAULT_CREDS_PATH = os.path.join(DEFAULT_CREDS_DIR, "credentials.json")
DEFAULT_TOKEN_PATH = os.path.join(DEFAULT_CREDS_DIR, "token.json")

START_DATE = date(2023, 11, 7)  # Invoice #1
VALID_DOCTYPES = {"INV", "PMT", "ACH", "DEP", "CRN", "ADJ"}

def ensure_creds(creds_path: str = DEFAULT_CREDS_PATH, token_path: str = DEFAULT_TOKEN_PATH) -> Credentials:
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())
    return creds

def read_sheet_values(service, spreadsheet_id: str, tab_name: str) -> pd.DataFrame:
    """Read a tab as a headered table into a DataFrame, padding short rows."""
    rng = f"{tab_name}!A:Z"
    resp = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute()
    values = resp.get("values", [])
    if not values:
        return pd.DataFrame()
    header = values[0]
    rows = values[1:]

    # Normalize all rows to same length
    ncols = len(header)
    normalized = [r + [""] * (ncols - len(r)) if len(r) < ncols else r[:ncols] for r in rows]

    df = pd.DataFrame(normalized, columns=header)
    return df


def write_email_drafts(service, spreadsheet_id: str, rows):
    sheet = service.spreadsheets()
    meta = sheet.get(spreadsheetId=spreadsheet_id).execute()
    sheets = meta.get("sheets", [])
    sheet_by_title = {s["properties"]["title"]: s for s in sheets}

    if "EmailDrafts" not in sheet_by_title:
        add_req = {"addSheet": {"properties": {"title": "EmailDrafts"}}}
        sheet.batchUpdate(spreadsheetId=spreadsheet_id, body={"requests":[add_req]}).execute()
    else:
        sheet.values().clear(spreadsheetId=spreadsheet_id, range="EmailDrafts!A:Z").execute()

    header = [["Date","Subject","Body","Comments","Recipients","Approved?","Sent?","Venue"]]
    data = header + rows
    sheet.values().update(
        spreadsheetId=spreadsheet_id,
        range="EmailDrafts!A1",
        valueInputOption="RAW",
        body={"values": data}
    ).execute()

def parse_money(x):
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", "").replace("$", "")
    if s == "":
        return 0.0
    try:
        return float(s)
    except:
        return 0.0

def numeric_prefix(docnbr):
    if docnbr is None:
        return None
    s = str(docnbr).strip()
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None

def derive_invoice_date(docnbr):
    n = numeric_prefix(docnbr)
    if n is None:
        return None
    return START_DATE + timedelta(days=(n - 1))

def normalize_venue_from_account(account):
    if not isinstance(account, str):
        return ""
    a = account.strip()
    if a.lower().startswith("rcvbls "):
        return a[7:].strip()
    return a

def build_collections(service, spreadsheet_id, journal_tab, rcvbles_tab, today, test_mode):
    gl = read_sheet_values(service, spreadsheet_id, journal_tab)
    rc = read_sheet_values(service, spreadsheet_id, rcvbles_tab)

    for col in ["Seq","Date","Description","Account","Debit","Credit","DocType","DocNbr","ExtDoc"]:
        if col not in gl.columns:
            gl[col] = ""

    gl["DebitF"] = gl["Debit"].map(parse_money)
    gl["CreditF"] = gl["Credit"].map(parse_money)

    gl["DocType"] = gl["DocType"].fillna("").str.upper().str.strip()
    gl = gl[gl["DocType"].isin(VALID_DOCTYPES) | (gl["DocType"]=="")]

    inv_rows = gl[gl["DocType"]=="INV"].copy()
    inv_rows["Venue"] = inv_rows["Account"].map(normalize_venue_from_account)
    inv_rows["InvoiceNbr"] = inv_rows["DocNbr"]
    inv_rows["InvoiceDate"] = inv_rows["DocNbr"].map(derive_invoice_date)
    inv_rows["InvoiceAmt"] = (inv_rows["DebitF"] - inv_rows["CreditF"]).round(2)
    inv_rows = inv_rows[inv_rows["InvoiceAmt"] > 0]

    pay_rows = gl[gl["DocType"].isin({"PMT","ACH","DEP","CRN","ADJ"})].copy()
    pay_rows["Venue"] = pay_rows["Account"].map(normalize_venue_from_account)
    pay_rows["Applied"] = (pay_rows["CreditF"] - pay_rows["DebitF"]).round(2)
    pay_rows = pay_rows[pay_rows["Account"].astype(str).str.lower().str.startswith("rcvbls ")]

    payments_by_inv = (
        pay_rows.groupby(["Venue","DocNbr"], dropna=False)["Applied"]
        .sum()
        .reset_index()
        .rename(columns={"DocNbr":"InvoiceNbr","Applied":"TotalPayments"})
    )

    inv = inv_rows.merge(payments_by_inv, on=["Venue","InvoiceNbr"], how="left")
    inv["TotalPayments"] = inv["TotalPayments"].fillna(0.0)
    inv["Balance"] = (inv["InvoiceAmt"] - inv["TotalPayments"]).round(2)

    inv["InvoiceDate"] = pd.to_datetime(inv["InvoiceDate"])
    base_today = pd.to_datetime(str(today))
    inv["AgeDays"] = (base_today - inv["InvoiceDate"]).dt.days

    open_inv = inv[inv["Balance"] > 0.0].copy()

    # Merge contact info
    rc_cols = {
        "ARVenue":"ARVenue",
        "ARContact":"ARContact",
        "ARFirst Name":"ARFirstName",
        "ARCellPhone":"ARCellPhone",
        "ARWorkPhone":"ARWorkPhone"
    }
    for c in rc_cols:
        if c not in rc.columns:
            rc[c] = ""
    rc_small = rc[list(rc_cols.keys())].rename(columns=rc_cols).drop_duplicates()
    open_inv = open_inv.merge(rc_small, left_on="Venue", right_on="ARVenue", how="left")

    # Build payment detail strings per invoice
    def payment_details_for(venue, inv_nbr):
        subset = pay_rows[(pay_rows["Venue"]==venue) & (pay_rows["DocNbr"]==inv_nbr)]
        out = []
        for _, r in subset.iterrows():
            d = str(r.get("Date",""))
            ref = str(r.get("ExtDoc","")).strip()
            amt = r.get("CreditF",0.0) if r.get("CreditF",0.0)>0 else (r.get("DebitF",0.0)*-1)
            out.append(f"{d} · {ref} · ${round(abs(amt))}" if ref else f"{d} · ${round(abs(amt))}")
        return out

    open_inv["PaymentsList"] = open_inv.apply(lambda r: payment_details_for(r["Venue"], r["InvoiceNbr"]), axis=1)

    # Group by venue and compose email drafts
    venue_groups = []
    for venue, grp in open_inv.sort_values(["Venue","InvoiceDate"]).groupby("Venue"):
        total_balance = int(round(grp["Balance"].sum()))
        over30 = int(((grp["AgeDays"]>=30) & (grp["Balance"]>0)).sum())

        pays_for_venue = pay_rows[pay_rows["Venue"]==venue].copy()
        last_payment_str = "No payments on record"
        if len(pays_for_venue):
            def to_dt(s):
                try: return pd.to_datetime(s)
                except: return pd.NaT
            pays_for_venue["Dt"] = pays_for_venue["Date"].map(to_dt)
            pays_for_venue = pays_for_venue.sort_values("Dt")
            last = pays_for_venue.iloc[-1]
            last_payment_str = f"{last.get('Date','')} ({str(last.get('ExtDoc','')).strip()})"

        # Table lines
        lines = []
        for _, r in grp.iterrows():
            inv_n = str(r["InvoiceNbr"])
            inv_dt = pd.to_datetime(r["InvoiceDate"]).strftime("%Y-%m-%d")
            amt = int(round(r["InvoiceAmt"]))
            bal = int(round(r["Balance"]))
            age = int(r["AgeDays"])
            overdue_note = " (60+)" if age>=60 else (" (30+)" if age>=30 else "")
            pays = "; ".join(r["PaymentsList"]) if r["PaymentsList"] else "—"
            lines.append(f"{inv_n} | {inv_dt} | ${amt} | {pays} | ${bal} | {age}d{overdue_note}")

        # Contact fields
        first = grp.iloc[0]
        contact_name = str(first.get("ARFirstName") or first.get("ARContact") or "").strip()

        subject = "Friendly update on your Mixed Nuts performance invoices"
        intro_name = contact_name if contact_name else "there"
        summary_line = f"Total outstanding balance for {venue} = ${total_balance}. {over30} invoice(s) over 30 days."
        if last_payment_str != "No payments on record":
            summary_line += f" Last payment received {last_payment_str}."

        body_lines = [
            f"Hi {intro_name},",
            "",
            "I hope you’re doing well! I wanted to share a quick summary of our open invoice(s) for your location:",
            summary_line,
            "",
            "Details:",
            "Invoice # | Invoice Date | Amount | Payments (date · ref · amount) | Balance Due | Age",
            "---|---|---|---|---|---",
            *lines,
            "",
            "Please let me know if you have any questions or if payment has already been processed.",
            "",
            "Thanks so much,",
            "Keith Day",
            "Legacy Performers / The Mixed Nuts",
            "📞 385-377-0451 (call or text anytime)"
        ]
        body_text = "\n".join(body_lines)

        recipients = "keith.day@legacyperformers.org" if test_mode else ""
        venue_groups.append([
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            subject,
            body_text,
            "Auto-generated by collections_report_generator.py",
            recipients,
            "",  # Approved?
            "",  # Sent?
            venue
        ])
    return venue_groups

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spreadsheet", required=True)
    parser.add_argument("--journal-tab", default="GenEnt")
    parser.add_argument("--rcvbles-tab", default="Rcvbles")
    parser.add_argument("--write-email-drafts", action="store_true")
    parser.add_argument("--output-emails", action="store_true")
    parser.add_argument("--today", default=None)
    parser.add_argument("--creds", default=None)
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()

    # Prepare auth
    creds_path = args.creds if args.creds else os.path.join(os.path.expanduser("~"), ".config", "mixed_nuts_gsheets", "credentials.json")
    token_path = os.path.join(os.path.dirname(creds_path), "token.json")

    # Ensure credentials
    from google.oauth2.credentials import Credentials as _C
    from google.auth.transport.requests import Request as _R
    from google_auth_oauthlib.flow import InstalledAppFlow as _F
    if not os.path.exists(os.path.dirname(token_path)):
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
    creds = None
    if os.path.exists(token_path):
        creds = _C.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(_R())
        else:
            flow = _F.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    service = build("sheets", "v4", credentials=creds)

    # Set "today"
    if args.today:
        try:
            today = datetime.strptime(args.today, "%Y-%m-%d").date()
        except Exception:
            today = date.today()
    else:
        today = date.today()

    # Build drafts
    drafts = build_collections(service, args.spreadsheet, args.journal_tab, args.rcvbles_tab, today, args.test_mode)

    # Write EmailDrafts tab
    if args.write_email_drafts:
        write_email_drafts(service, args.spreadsheet, drafts)
        print(f"Wrote {len(drafts)} rows to EmailDrafts.")

    # Optionally write .txt files
    if args.output_emails:
        out_dir = os.path.join(os.getcwd(), "output", "emails")
        os.makedirs(out_dir, exist_ok=True)
        count = 0
        for row in drafts:
            venue = row[-1]
            fname = re.sub(r"[^A-Za-z0-9_.-]+", "_", venue) or "venue"
            path = os.path.join(out_dir, f"{fname}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Subject: {row[1]}\n\n{row[2]}")
            count += 1
        print(f"Wrote {count} .txt files to {out_dir}")

if __name__ == "__main__":
    main()
