#!/usr/bin/env python3
"""
email_merge_v3.py — Dynamic YAMM-style email merge using Google Sheets + Google Doc templates.

NEW IN V3:
- Template lookup from a "DocLink" sheet.
- Supports multi-template mapping from a DocLink tab.
- Auto-exports templates to HTML and sends via Gmail.

NEW IN V3.2 (Nov 2025):
- Added `--debug` flag for optional detailed logging and HTML dumps.
  When enabled, intermediate HTML files and API operations are logged
  to help diagnose formatting or authentication issues.

(c) 2025 Keith Day / ChatGPT
"""

import argparse
import base64
import io
import os
import re
import sys
from datetime import datetime
from typing import Dict, Tuple, Optional

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Google APIs
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# ---------------- CONFIG ----------------
DEFAULT_CREDENTIALS_FILE = os.environ.get(
    "GOOGLE_OAUTH_CLIENT",
    "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
)
TOKEN_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/email_merge_v3_token.json"
DOC_LINK_TAB_NAME = "DocLink"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# ---------------- LOGGING HELPERS ----------------

def info(msg): print(f"[INFO]  {msg}")
def warn(msg): print(f"[WARN]  {msg}")
def error(msg): print(f"[ERROR] {msg}", file=sys.stderr)
def now_stamp() -> str: return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def dbg(debug_enabled: bool, msg: str):
    """Prints debug info only when debug mode is active."""
    if debug_enabled:
        print(f"[DEBUG] {msg}")

# ---------------- AUTH ----------------

def get_credentials(credentials_file: str, token_file: str, debug=False) -> Credentials:
    creds = None
    if os.path.exists(token_file):
        dbg(debug, f"Loading cached credentials from {token_file}")
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            dbg(debug, "Refreshing expired credentials")
            creds.refresh(Request())
        else:
            dbg(debug, "Running OAuth flow to obtain new credentials")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())
            dbg(debug, f"Saved refreshed token to {token_file}")
    return creds

# ---------------- SHEETS ----------------

def load_sheet_rows(sheets_service, sheet_id: str, a1_range: str, debug=False):
    dbg(debug, f"Fetching sheet range: {a1_range}")
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=a1_range
    ).execute()
    values = result.get("values", [])
    if not values:
        raise RuntimeError("Sheet range returned no values.")
    headers = values[0]
    rows = values[1:]
    dbg(debug, f"Loaded {len(rows)} data rows, {len(headers)} headers")
    return headers, rows

def update_sheet_cell(sheets_service, sheet_id: str, a1_cell: str, value: str, debug=False):
    dbg(debug, f"Updating sheet cell {a1_cell} with value '{value}'")
    body = {"values": [[value]]}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=a1_cell,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def load_doclink_map(sheets_service, sheet_id: str, debug=False) -> Dict[str, str]:
    try:
        dbg(debug, f"Loading DocLink tab: {DOC_LINK_TAB_NAME}")
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"{DOC_LINK_TAB_NAME}!A2:C"
        ).execute()
    except HttpError as e:
        error(f"Could not load DocLink tab: {e}")
        return {}
    rows = result.get("values", [])
    mapping = {}
    for r in rows:
        if len(r) < 2:
            continue
        name, link = r[0].strip(), r[1].strip()
        if name and link:
            mapping[name] = extract_doc_id_from_url(link) or link
    dbg(debug, f"Loaded {len(mapping)} templates from DocLink")
    return mapping

# ---------------- DRIVE ----------------

def export_doc_as_html(drive_service, doc_id: str, debug=False) -> str:
    dbg(debug, f"Exporting Google Doc {doc_id} as HTML")
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/html")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    html = buf.read().decode("utf-8", errors="replace")
    dbg(debug, f"Downloaded {len(html)} bytes of HTML")
    return html

def export_doc_as_pdf_bytes(drive_service, doc_id: str, debug=False) -> Tuple[bytes, str]:
    meta = drive_service.files().get(fileId=doc_id, fields="id, name, mimeType").execute()
    name, mimeType = meta.get("name", "Attachment"), meta.get("mimeType", "")
    dbg(debug, f"Exporting attachment '{name}' ({mimeType})")
    buf = io.BytesIO()
    if mimeType.startswith("application/vnd.google-apps"):
        request = drive_service.files().export_media(fileId=doc_id, mimeType="application/pdf")
    else:
        request = drive_service.files().get_media(fileId=doc_id)
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    data = buf.read()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dbg(debug, f"Exported PDF bytes: {len(data)} bytes, filename: {name}")
    return data, name

# ---------------- UTILITIES ----------------

def extract_doc_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None

PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+?)\s*}}")

def substitute_placeholders(text: str, row_dict: Dict[str, str], *, warn_subject_blanks=False, context=""):
    warnings, errors = [], []
    def repl(m):
        key = m.group(1).strip()
        if key not in row_dict:
            errors.append(f"Missing column {key} in {context}")
            return m.group(0)
        val = row_dict.get(key, "")
        if warn_subject_blanks and not val.strip():
            warnings.append(f"Blank subject value for {key} in {context}")
            return ""
        return val
    return PLACEHOLDER_RE.sub(repl, text), warnings, errors

def colnum_to_a1(n: int) -> str:
    """Convert a 1-based column index to Excel-style A1 notation."""
    result = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result

# ---------------- EMAIL ----------------

def build_email(to_email, subject, body, attachments, *, html=False, debug=False):
    dbg(debug, f"Building email to {to_email} with {len(attachments)} attachments")
    if attachments:
        msg = MIMEMultipart()
        msg["To"], msg["Subject"] = to_email, subject
        msg.attach(MIMEText(body, "html" if html else "plain"))
        for data, fname in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(part)
        return msg.as_bytes()
    else:
        msg = MIMEText(body, "html" if html else "plain")
        msg["To"], msg["Subject"] = to_email, subject
        return msg.as_bytes()

def gmail_send(gmail_service, raw_bytes: bytes, debug=False):
    dbg(debug, "Sending email via Gmail API")
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

# ---------------- MAIN ----------------

def main():
    parser = argparse.ArgumentParser(description="Email merge V3 with DocLink templates and debug logging.")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS_FILE)
    parser.add_argument("--token", default=TOKEN_FILE)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument("--range", required=True)
    parser.add_argument("--to-col", required=True)
    parser.add_argument("--selector-col", required=True)
    parser.add_argument("--template-col", default="Template")
    parser.add_argument("--att-col", action="append", default=[])
    parser.add_argument("--mode", choices=["test", "final"], default="test")
    parser.add_argument("--test-to")
    parser.add_argument("--only-row", type=int)
    parser.add_argument("--rate-sleep", type=float, default=0.0)
    parser.add_argument("--prompt-each", choices=["y", "n"], default="n")
    parser.add_argument("--prompt-col", default=None)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging and raw HTML dumps")
    args = parser.parse_args()

    if args.mode == "test" and not args.test_to:
        parser.error("--test-to required in test mode")

    debug = args.debug

    creds = get_credentials(args.credentials, args.token, debug)
    sheets_service = build("sheets", "v4", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)

    doclink_map = load_doclink_map(sheets_service, args.sheet_id, debug)
    info(f"Loaded {len(doclink_map)} template(s) from DocLink tab.")

    headers, data_rows = load_sheet_rows(sheets_service, args.sheet_id, args.range, debug)
    header_to_idx = {h: i for i, h in enumerate(headers)}

    for needed in [args.to_col, args.selector_col, args.template_col]:
        if needed not in header_to_idx:
            raise RuntimeError(f"Required column '{needed}' not found in headers.")

    prompt_each = args.prompt_each.lower().startswith("y")
    prompt_col_name = args.prompt_col

    total = sent = skipped = errors_count = 0
    base_visible_row_index = 2

    for r_index, row in enumerate(data_rows, start=1):
        total += 1
        visible_row_number = base_visible_row_index + r_index - 1
        row_dict = {h: (row[i] if i < len(row) else "") for h, i in header_to_idx.items()}

        if args.only_row and visible_row_number != args.only_row:
            continue

        sel_val = row_dict.get(args.selector_col, "").strip()
        if sel_val.lower().startswith("test sent") or re.match(r"^\d{4}-\d{2}-\d{2}", sel_val):
            skipped += 1
            continue
        if sel_val.upper() not in {"Y", "READY"}:
            skipped += 1
            continue

        to_email = (args.test_to if args.mode == "test" else row_dict.get(args.to_col, "")).strip()
        if not to_email:
            error(f"Row {visible_row_number}: missing recipient email")
            continue

        template_name = row_dict.get(args.template_col, "").strip()
        template_id = doclink_map.get(template_name)
        if not template_id:
            warn(f"Row {visible_row_number}: template '{template_name}' not found in DocLink -> SKIP")
            continue

        dbg(debug, f"Row {visible_row_number}: Using template '{template_name}' ({template_id})")

        body_template = export_doc_as_html(drive_service, template_id, debug)

        # Dump raw HTML if debugging
        if debug:
            raw_path = f"/tmp/raw_email_row{visible_row_number}.html"
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(body_template)
            dbg(debug, f"Wrote raw HTML to {raw_path}")

        # Cleanup HTML
        body_template = re.sub(r"<style.*?>.*?</style>", "", body_template, flags=re.DOTALL | re.IGNORECASE)
        body_template = re.sub(r'style="[^"]*margin[^"]*"', "", body_template, flags=re.IGNORECASE)
        body_template = re.sub(r'max-width:[^;"]*;?', '', body_template, flags=re.IGNORECASE)
        body_template = re.sub(r'padding:[^;"]*;?', '', body_template, flags=re.IGNORECASE)

        if debug:
            clean_path = f"/tmp/clean_email_row{visible_row_number}.html"
            with open(clean_path, "w", encoding="utf-8") as f:
                f.write(body_template)
            dbg(debug, f"Wrote cleaned HTML to {clean_path}")

        meta = drive_service.files().get(fileId=template_id, fields="name").execute()
        subject_template = meta.get("name", "(Untitled Template)")
        subject, _, _ = substitute_placeholders(subject_template or "", row_dict, warn_subject_blanks=True)

        # ✅ Prepend [TEST] to subject line in test mode
        if args.mode == "test":
            subject = f"[TEST] {subject}"

        body, _, _ = substitute_placeholders(body_template or "", row_dict)

        attachments = []
        for att_col in args.att_col:
            if att_col in header_to_idx:
                doc_link = row_dict.get(att_col, "").strip()
                if doc_link:
                    doc_id = extract_doc_id_from_url(doc_link) or doc_link
                    try:
                        data, fname = export_doc_as_pdf_bytes(drive_service, doc_id, debug)
                        attachments.append((data, fname))
                        info(f"Row {visible_row_number}: attaching {fname}")
                    except HttpError as e:
                        warn(f"Row {visible_row_number}: failed to export attachment -> {e}")

        if prompt_each:
            prompt_info = row_dict.get(prompt_col_name, "") if prompt_col_name else ""
            print(f"\nRow {visible_row_number}: about to send to {to_email}")
            if prompt_info:
                print(f"Prompt info ({prompt_col_name}): {prompt_info}")
            choice = input("Send this email? (y/n, default y): ").strip().lower() or "y"
            if choice not in ("y", "yes"):
                info(f"Row {visible_row_number}: skipped by user choice")
                skipped += 1
                continue

        raw_bytes = build_email(to_email, subject, body, attachments, html=True, debug=debug)
        gmail_send(gmail_service, raw_bytes, debug)
        sent += 1
        info(f"Row {visible_row_number}: SENT to {to_email} | Subject: {subject}")

        # --- UPDATED SECTION: safely update selector column with send date ---
        stamp = f"TEST SENT {now_stamp()}" if args.mode == "test" else now_stamp()
        sel_col_idx = header_to_idx[args.selector_col] + 1
        sel_col_letter = colnum_to_a1(sel_col_idx)
        sheet_name = args.range.split('!')[0]
        a1_cell = f"{sheet_name}!{sel_col_letter}{visible_row_number}"
        update_sheet_cell(sheets_service, args.sheet_id, a1_cell, stamp, debug)
        # ---------------------------------------------------------------

    info("---- SUMMARY ----")
    info(f"Processed: {total}")
    info(f"Sent:      {sent}")
    info(f"Skipped:   {skipped}")
    info(f"Errors:    {errors_count}")
    info("Done.")

if __name__ == "__main__":
    main()
