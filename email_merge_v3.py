#!/usr/bin/env python3
"""
email_merge_v3.py — Dynamic YAMM-style email merge using Google Sheets + Google Doc templates.

NEW IN V3:
- Template lookup from a "DocLink" sheet.
  Each row in that tab should look like:
    Template | Link | Comment
  Example:
    INVOICE  | https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQr/edit | Standard invoice template
- Your main sheet should have a "Template" column with one of the names from DocLink!A2:A.
- The full URL or Doc ID works for the Link.
- The program no longer takes --template-doc-id as an argument.

(c) 2025 Keith Day / ChatGPT
"""

import argparse
import base64
import io
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Optional

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
# Use a dedicated token so this script’s OAuth scopes don't collide with other tools
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

# ---------------- UTILS ----------------

def info(msg): print(f"[INFO]  {msg}")
def warn(msg): print(f"[WARN]  {msg}")
def error(msg): print(f"[ERROR] {msg}", file=sys.stderr)

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def extract_doc_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None

# ---------------- AUTH ----------------

def get_credentials(credentials_file: str = DEFAULT_CREDENTIALS_FILE, token_file: str = TOKEN_FILE) -> Credentials:
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())
    return creds

# ---------------- SHEETS HELPERS ----------------

def load_sheet_rows(sheets_service, sheet_id: str, a1_range: str):
    result = sheets_service.spreadsheets().values().get(
        spreadsheetId=sheet_id, range=a1_range
    ).execute()
    values = result.get("values", [])
    if not values:
        raise RuntimeError("Sheet range returned no values.")
    headers = values[0]
    rows = values[1:]
    return headers, rows

def update_sheet_cell(sheets_service, sheet_id: str, a1_cell: str, value: str):
    body = {"values": [[value]]}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=a1_cell,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def load_doclink_map(sheets_service, sheet_id: str) -> Dict[str, str]:
    """Reads DocLink tab → returns {template_name: doc_id_or_link}"""
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=sheet_id,
            range=f"{DOC_LINK_TAB_NAME}!A2:C"
        ).execute()
    except HttpError as e:
        error(f"Could not load DocLink tab: {e}")
        return {}
    rows = result.get("values", [])
    mapping = {}
    for r in rows:
        if len(r) < 2:
            continue
        name = r[0].strip()
        link = r[1].strip()
        if name and link:
            mapping[name] = extract_doc_id_from_url(link) or link
    return mapping

# ---------------- DRIVE HELPERS ----------------

def export_doc_as_text(drive_service, doc_id: str) -> str:
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/plain")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8", errors="replace")

def export_doc_as_html(drive_service, doc_id: str) -> str:
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/html")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8", errors="replace")

def export_doc_as_pdf_bytes(drive_service, doc_id: str) -> Tuple[bytes, str]:
    meta = drive_service.files().get(fileId=doc_id, fields="id, name, mimeType").execute()
    mimeType = meta.get("mimeType", "")
    name = meta.get("name", "Attachment")
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
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return buf.read(), name

# ---------------- TEMPLATE PARSING ----------------

PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+?)\s*}}")

def split_subject_and_body(template_text: str):
    lines = template_text.splitlines()
    subject = None
    subject_idx = None
    for i, line in enumerate(lines):
        cleaned = line.lstrip("\ufeff").strip()
        if cleaned.lower().startswith("subject:"):
            subject = cleaned.split(":", 1)[1].strip()
            subject_idx = i
            break
    body = "\n".join(lines[subject_idx + 1:]).lstrip("\n") if subject_idx is not None else template_text
    return subject, body

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

# ---------------- EMAIL ----------------

def build_email(to_email, subject, body, attachments, *, html=False):
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

def gmail_send(gmail_service, raw_bytes: bytes):
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

def col_letter_to_index(letter: str) -> int:
    letter = letter.upper()
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n

def index_to_col_letter(index: int) -> str:
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result

def a1_for_cell(range_a1: str, row_idx_1based: int, col_idx_1based: int) -> str:
    """
    Compute a proper A1 reference (Sheet!ColRow) for a given data cell.
    Works reliably even if the base range omits row numbers (e.g. 'A:Z' or 'A1:BH').
    """
    sheet_name = ""
    if "!" in range_a1:
        sheet_name, range_part = range_a1.split("!", 1)
    else:
        range_part = range_a1

    # Extract first column from the left edge of range (default A1)
    left = range_part.split(":")[0]
    m = re.match(r"([A-Za-z]+)(\d*)", left)
    base_col_letter = m.group(1) if m else "A"
    base_row = int(m.group(2)) if (m and m.group(2)) else 1

    base_col_idx = col_letter_to_index(base_col_letter)
    target_col_letter = index_to_col_letter(base_col_idx + col_idx_1based - 1)
    target_row = base_row + row_idx_1based - 1

    a1_ref = f"{target_col_letter}{target_row}"
    return f"{sheet_name}!{a1_ref}" if sheet_name else a1_ref


# ---------------- MAIN ----------------

def main():
    parser = argparse.ArgumentParser(description="Email merge V3: dynamic template lookup via DocLink tab.")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS_FILE)
    parser.add_argument("--token", default=TOKEN_FILE)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument("--range", required=True)
    parser.add_argument("--to-col", required=True)
    parser.add_argument("--selector-col", required=True)
    parser.add_argument("--template-col", default="Template", help="Column header name containing the template name (default: Template)")
    parser.add_argument("--att-col", action="append", default=[])
    parser.add_argument("--mode", choices=["test", "final"], default="test")
    parser.add_argument("--test-to")
    parser.add_argument("--only-row", type=int)
    parser.add_argument("--rate-sleep", type=float, default=0.0)
    args = parser.parse_args()

    if args.mode == "test" and not args.test_to:
        parser.error("--test-to required in test mode")

    creds = get_credentials(args.credentials, args.token)
    sheets_service = build("sheets", "v4", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)

    doclink_map = load_doclink_map(sheets_service, args.sheet_id)
    info(f"Loaded {len(doclink_map)} template(s) from DocLink tab.")

    headers, data_rows = load_sheet_rows(sheets_service, args.sheet_id, args.range)
    header_to_idx = {h: i for i, h in enumerate(headers)}

    for needed in [args.to_col, args.selector_col, args.template_col]:
        if needed not in header_to_idx:
            raise RuntimeError(f"Required column '{needed}' not found in headers.")

    total = sent = skipped = errors_count = 0
    base_visible_row_index = 2

    for r_index, row in enumerate(data_rows, start=1):
        total += 1
        visible_row_number = base_visible_row_index + r_index - 1

        row_dict = {h: (row[i] if i < len(row) else "") for h, i in header_to_idx.items()}
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

        # Load template (HTML body + use Doc name as subject, with substitutions)
        meta = drive_service.files().get(fileId=template_id, fields="name").execute()
        subject_template = meta.get("name", "(Untitled Template)")

        # Export HTML body
        body_template = export_doc_as_html(drive_service, template_id)

        # Clean up HTML (remove embedded styles/margins)
        body_template = re.sub(r"<style.*?>.*?</style>", "", body_template, flags=re.DOTALL | re.IGNORECASE)
        body_template = re.sub(r'style="[^"]*margin[^"]*"', "", body_template, flags=re.IGNORECASE)

        # Apply substitutions
        subject, _, _ = substitute_placeholders(subject_template or "", row_dict, warn_subject_blanks=True, context=f"row {visible_row_number} subject")
        body, _, _ = substitute_placeholders(body_template or "", row_dict, context=f"row {visible_row_number} body")



        attachments = []
        for att_col in args.att_col:
            if att_col in header_to_idx:
                doc_link = row_dict.get(att_col, "").strip()
                if doc_link:
                    doc_id = extract_doc_id_from_url(doc_link) or doc_link
                    try:
                        data, fname = export_doc_as_pdf_bytes(drive_service, doc_id)
                        attachments.append((data, fname))
                        info(f"Row {visible_row_number}: attaching {fname}")
                    except HttpError as e:
                        warn(f"Row {visible_row_number}: failed to export attachment -> {e}")

        raw_bytes = build_email(to_email, subject, body, attachments, html=True)
        gmail_send(gmail_service, raw_bytes)
        sent += 1
        info(f"Row {visible_row_number}: SENT to {to_email} | Subject: {subject}")

        stamp = f"TEST SENT {now_stamp()}" if args.mode == "test" else now_stamp()
        sel_col_idx = header_to_idx[args.selector_col] + 1
        a1_cell = a1_for_cell(args.range, visible_row_number, sel_col_idx)
        update_sheet_cell(sheets_service, args.sheet_id, a1_cell, stamp)
        info(f"Row {visible_row_number}: wrote stamp to {a1_cell}")

    info("---- SUMMARY ----")
    info(f"Processed: {total}")
    info(f"Sent:      {sent}")
    info(f"Skipped:   {skipped}")
    info(f"Errors:    {errors_count}")
    info("Done.")

if __name__ == "__main__":
    main()
