#!/usr/bin/env python3
"""
mail_merg_v2.py — V2 email merge system using Google Sheets + Google Docs + Gmail.

Key Improvements:
- Subject is taken directly from the Google Doc's title (not from "Subject:" line in body).
- Automatically prepends [TEST] in test mode.
- Cleaned HTML export handling (no more subject-line stripping logic).
- Retains {{ColumnName}} substitutions, PDF attachments, and sheet timestamping.

(c) Refactored V2 by ChatGPT for Keith Day / Legacy Performers
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
DEFAULT_CREDENTIALS_FILE = os.environ.get(
    "GOOGLE_OAUTH_CLIENT",
    "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
)

# Use a dedicated token file for this version
TOKEN_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token_email_merge_v2.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


# ---------------- UTILS ----------------
def debug(msg: str): print(f"[DEBUG] {msg}")
def info(msg: str): print(f"[INFO]  {msg}")
def warn(msg: str): print(f"[WARN]  {msg}")
def error(msg: str): print(f"[ERROR] {msg}", file=sys.stderr)

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def extract_doc_id_from_url(url: str) -> Optional[str]:
    if not url: return None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None

def get_credentials(credentials_file: str = DEFAULT_CREDENTIALS_FILE, token_file: str = TOKEN_FILE) -> Credentials:
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())  # type: ignore[name-defined]
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as token:
            token.write(creds.to_json())
    return creds

# ---------------- GOOGLE HELPERS ----------------
def load_sheet_rows(sheets_service, sheet_id: str, a1_range: str) -> Tuple[List[str], List[List[str]]]:
    result = sheets_service.spreadsheets().values().get(spreadsheetId=sheet_id, range=a1_range).execute()
    values = result.get("values", [])
    if not values: raise RuntimeError("Sheet range returned no values.")
    headers, rows = values[0], values[1:]
    return headers, rows

def update_sheet_cell(sheets_service, sheet_id: str, a1_cell: str, value: str):
    body = {"values": [[value]]}
    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range=a1_cell,
        valueInputOption="USER_ENTERED",
        body=body
    ).execute()

def col_letter_to_index(letter: str) -> int:
    letter = letter.upper()
    n = 0
    for ch in letter: n = n * 26 + (ord(ch) - ord('A') + 1)
    return n

def index_to_col_letter(index: int) -> str:
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result

def a1_for_cell(range_a1: str, row_idx_1based: int, col_idx_1based: int) -> str:
    if "!" in range_a1:
        sheet_name, cols = range_a1.split("!", 1)
    else:
        sheet_name, cols = "", range_a1
    left = cols.split(":")[0]
    m = re.match(r"([A-Za-z]+)(\d+)", left)
    base_col_letter, base_row = (m.group(1), int(m.group(2))) if m else ("A", 1)
    base_col_idx = col_letter_to_index(base_col_letter)
    target_col_letter = index_to_col_letter(base_col_idx + col_idx_1based - 1)
    target_row = base_row + row_idx_1based - 1
    return f"{sheet_name+'!' if sheet_name else ''}{target_col_letter}{target_row}"

def export_doc_as_html(drive_service, doc_id: str) -> str:
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/html")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done: status, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8", errors="replace")

def export_doc_as_pdf_bytes(drive_service, doc_id: str) -> Tuple[bytes, str]:
    meta = drive_service.files().get(fileId=doc_id, fields="id,name,mimeType").execute()
    mimeType = meta.get("mimeType", "")
    name = meta.get("name", "Attachment")
    buf = io.BytesIO()
    request = (
        drive_service.files().export_media(fileId=doc_id, mimeType="application/pdf")
        if mimeType.startswith("application/vnd.google-apps")
        else drive_service.files().get_media(fileId=doc_id)
    )
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done: status, done = downloader.next_chunk()
    buf.seek(0)
    if not name.lower().endswith(".pdf"): name += ".pdf"
    return buf.read(), name

# ---------------- TEMPLATE PARSING ----------------
PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+?)\s*}}")

def substitute_placeholders(text: str, row_dict: Dict[str, str], warn_subject_blanks: bool = False, context: str = "") -> Tuple[str, List[str], List[str]]:
    warnings, errors = [], []
    def repl(m):
        key = m.group(1).strip()
        if key not in row_dict:
            errors.append(f"Missing column for placeholder {{ {key} }} in {context}")
            return m.group(0)
        val = row_dict.get(key, "")
        if warn_subject_blanks and not str(val).strip():
            warnings.append(f"Blank subject value for {{ {key} }} in {context}")
            return ""
        return str(val) if val is not None else ""
    return PLACEHOLDER_RE.sub(repl, text), warnings, errors

# ---------------- EMAIL SENDING ----------------
def build_email(to_email: str, subject: str, body: str, attachments: List[Tuple[bytes, str]], *, body_as_html: bool) -> bytes:
    if attachments:
        msg = MIMEMultipart()
        msg["To"], msg["Subject"] = to_email, subject
        msg.attach(MIMEText(body, "html" if body_as_html else "plain"))
        for data, fname in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(part)
        return msg.as_bytes()
    else:
        msg = MIMEText(body, "html" if body_as_html else "plain")
        msg["To"], msg["Subject"] = to_email, subject
        return msg.as_bytes()

def gmail_send(gmail_service, raw_bytes: bytes):
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

# ---------------- MAIN ----------------
print(">>> Running mail_merg_v2.py")

def main():
    parser = argparse.ArgumentParser(description="Email merge V2: Google Sheets + Google Doc title as subject + Gmail send.")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS_FILE)
    parser.add_argument("--token", default=TOKEN_FILE)
    parser.add_argument("--sheet-id", required=True)
    parser.add_argument("--range", required=True)
    parser.add_argument("--to-col", required=True)
    parser.add_argument("--selector-col", required=True)
    parser.add_argument("--template-doc-id", required=True)
    parser.add_argument("--att-col", action="append", default=[])
    parser.add_argument("--mode", choices=["test", "final"], default="test")
    parser.add_argument("--test-to")
    parser.add_argument("--only-row", type=int)
    parser.add_argument("--body-as-html", action="store_true")
    parser.add_argument("--rate-sleep", type=float, default=0.0)
    args = parser.parse_args()

    if args.mode == "test" and not args.test_to:
        parser.error("--test-to is required when --mode test")

    args.body_as_html = True
    creds = get_credentials(args.credentials, args.token)
    sheets_service = build("sheets", "v4", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)

    headers, data_rows = load_sheet_rows(sheets_service, args.sheet_id, args.range)
    header_to_idx = {h: i for i, h in enumerate(headers)}
    for needed in [args.to_col, args.selector_col]:
        if needed not in header_to_idx:
            raise RuntimeError(f"Missing required column '{needed}'")

    # ---- SUBJECT FROM DOC TITLE ----
    try:
        meta = drive_service.files().get(fileId=args.template_doc_id, fields="name").execute()
        subject_template = meta.get("name", "").strip()
        if not subject_template:
            warn("Google Doc has no title; subject will be blank.")
        else:
            info(f"Using Google Doc title as subject: {subject_template!r}")
    except HttpError as e:
        error(f"Failed to retrieve Google Doc title: {e}")
        subject_template = ""

    # ---- BODY FROM DOC HTML ----
    try:
        body_template = export_doc_as_html(drive_service, args.template_doc_id)
        body_template = re.sub(r"<style.*?>.*?</style>", "", body_template, flags=re.DOTALL | re.IGNORECASE)
        def _clean_body_style(m):
            attrs, style = m.group(1) or "", m.group(2) or ""
            cleaned = re.sub(
                r"(?:\bmargin(?:-(?:left|right|top|bottom))?|\bpadding(?:-(?:left|right|top|bottom))?"
                r"|\bmax-width|\bwidth)\s*:\s*[^;\"']*;?", "", style, flags=re.IGNORECASE)
            cleaned = re.sub(r";\s*;", ";", cleaned).strip().strip(";")
            return f"<body{attrs} style=\"{cleaned}\">" if cleaned else f"<body{attrs}>"
        body_template = re.sub(r"<body([^>]*)\sstyle=\"([^\"]*)\">", _clean_body_style, body_template, count=1, flags=re.IGNORECASE)
    except HttpError as e:
        error(f"Failed to export Google Doc HTML: {e}")
        sys.exit(2)

    # ---- PREFIX [TEST] IF TEST MODE ----
    if args.mode == "test":
        subject_template = f"[TEST] {subject_template}"

    total = sent = skipped = errors_count = 0
    base_visible_row_index = 2

    for r_index, row in enumerate(data_rows, start=1):
        total += 1
        visible_row_number = base_visible_row_index + r_index - 1
        if args.only_row and visible_row_number != args.only_row:
            continue

        row_dict = {h: (row[i] if i < len(row) else "") for h, i in header_to_idx.items()}
        # --- Normalize selector value ---
        sel_val = (row_dict.get(args.selector_col, "") or "")
        # Remove weird Unicode spaces & control chars
        sel_val = (
            sel_val.replace("\u00A0", " ")  # non-breaking space
                   .replace("\u200B", "")   # zero-width space
                   .strip()
        )

        # Decide if this row should send
        normalized = sel_val.upper()

        if not normalized or normalized.startswith("TEST SENT") or \
           re.match(r"^\d{4}-\d{2}-\d{2}", normalized) or \
           normalized not in {"Y", "YES", "READY"}:
            skipped += 1
            continue


        to_email = (args.test_to if args.mode == "test" else row_dict.get(args.to_col, "")).strip()
        if not to_email:
            errors_count += 1
            continue

        subject, subj_warnings, subj_errors = substitute_placeholders(subject_template, row_dict, warn_subject_blanks=True, context=f"row {visible_row_number} subject")
        if subj_errors:
            errors_count += 1
            continue

        body, body_warnings, body_errors = substitute_placeholders(body_template, row_dict, context=f"row {visible_row_number} body")
        if body_errors:
            errors_count += 1
            continue

        attachments: List[Tuple[bytes, str]] = []
        for att_col in args.att_col:
            if att_col not in header_to_idx: continue
            doc_link = row_dict.get(att_col, "").strip()
            if not doc_link: continue
            doc_id = extract_doc_id_from_url(doc_link) or doc_link.strip()
            try:
                data, fname = export_doc_as_pdf_bytes(drive_service, doc_id)
                attachments.append((data, fname))
            except HttpError:
                warn(f"Row {visible_row_number}: failed to export attachment")

        raw_bytes = build_email(to_email, subject, body, attachments, body_as_html=args.body_as_html)
        try:
            gmail_send(gmail_service, raw_bytes)
            sent += 1
            info(f"Row {visible_row_number}: SENT to {to_email} | Subject: {subject!r}")
        except HttpError as e:
            errors_count += 1
            error(f"Row {visible_row_number}: Gmail send failed -> {e}")
            continue

        stamp = (f"TEST SENT {now_stamp()}" if args.mode == "test" else now_stamp())
        sel_col_idx1 = header_to_idx[args.selector_col] + 1
        cell_a1 = a1_for_cell(args.range, visible_row_number, sel_col_idx1)
        try:
            update_sheet_cell(sheets_service, args.sheet_id, cell_a1, stamp)
        except HttpError:
            warn(f"Row {visible_row_number}: failed to write stamp to sheet")

        if args.rate_sleep > 0:
            import time
            time.sleep(args.rate_sleep)

    info("---- SUMMARY ----")
    info(f"Processed: {total}")
    info(f"Sent:      {sent}")
    info(f"Skipped:   {skipped}")
    info(f"Errors:    {errors_count}")
    info("Done.")

if __name__ == "__main__":
    main()
