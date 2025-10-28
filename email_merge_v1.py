#!/usr/bin/env python3
"""
email_merge_v1.py — V1 single-file replacement for YAMM-like merges using Google Sheet rows,
a Google Doc template with {{ColumnName}} substitutions (including Subject: ... on the first line),
optional Google Doc attachments (exported to PDF), and Gmail sending.

USAGE (examples):
  python3 email_merge_v1.py \
    --sheet-id "SPREADSHEET_ID" \
    --range "Sheet1!A1:Z" \
    --to-col "Email" \
    --selector-col "Send?" \
    --template-doc-id "1AbCdEf..." \
    --att-col "Invoice Doc" \
    --att-col "Logistics Doc" \
    --mode test \
    --test-to "your.test.address@example.com"

  python3 email_merge_v1.py \
    --sheet-id "SPREADSHEET_ID" \
    --range "Sheet1!A1:Z" \
    --to-col "Email" \
    --selector-col "Send?" \
    --template-doc-id "1AbCdEf..." \
    --mode final

NOTES:
- Placeholders in the Google Doc must match column headers in the Sheet.
- The first line that begins with "Subject:" (case-insensitive) in the template Doc determines the subject.
  The remainder (after "Subject:") is the subject template and supports {{ColumnName}} substitutions.
  If missing, a warning is logged.
- For body placeholders with blank row values → replaced with empty string.
- For SUBJECT placeholders with blank row values → a WARNING is logged (but the row can still send).
- Selector column logic:
  - Process rows where selector column contains "Y" or "READY" (case-insensitive).
  - In test mode, the row is marked "TEST SENT <timestamp>" (but not finalized).
  - In final mode, the row is stamped with the current timestamp (ISO8601-like).
- To test only a single row, use --only-row with the 1-based row index as shown in the sheet (header is row 1).

AUTH:
- This script uses OAuth (Installed App). It will create/refresh token.json.
- Scopes: Sheets (read/write), Drive (readonly/export), Gmail (send).

LIMITS:
- The email body is sent as plain text by default. Use --body-as-html if your template contains HTML.
- The template Doc is exported as text/plain for parsing. That means template formatting
  in the Doc is not preserved automatically; consider storing HTML in the Doc if you want to send HTML.

(c) V1 by ChatGPT. Feel free to adapt.
"""

import argparse
import base64
import io
import os
import re
import sys
import re  

from datetime import datetime, timezone
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
# You must have a client_secret OAuth JSON (downloaded from Google Cloud) as credentials.json
# The token.json will be created automatically after the first run.
DEFAULT_CREDENTIALS_FILE = os.environ.get("GOOGLE_OAUTH_CLIENT", "credentials.json")
TOKEN_FILE = "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",       # read/write
    "https://www.googleapis.com/auth/drive.readonly",     # export/download
    "https://www.googleapis.com/auth/gmail.send",         # send email
]

# ---------------- UTILS ----------------

def debug(msg: str):
    print(f"[DEBUG] {msg}")  # stdout instead of stderr

def info(msg: str):
    print(f"[INFO]  {msg}")

def warn(msg: str):
    print(f"[WARN]  {msg}")

def error(msg: str):
    print(f"[ERROR] {msg}", file=sys.stderr)

def now_stamp() -> str:
    # ISO-like local timestamp (without timezone), for sheet marking
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def extract_doc_id_from_url(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return None

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
    """
    Returns (headers, rows). headers is the first row (strings), rows are subsequent rows.
    """
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

def col_letter_to_index(letter: str) -> int:
    """A -> 1, B -> 2, etc."""
    letter = letter.upper()
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n

def index_to_col_letter(index: int) -> str:
    """1 -> A, 2 -> B, ..."""
    result = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result

def a1_for_cell(range_a1: str, row_idx_1based: int, col_idx_1based: int) -> str:
    """
    Given the base range like 'Sheet1!A1:Z', compute the A1 address for a single cell in that sheet.
    We assume the sheet name and the leftmost column of the given range to compute offset.
    """
    if "!" in range_a1:
        sheet_name, cols = range_a1.split("!", 1)
    else:
        sheet_name, cols = "", range_a1
    # Parse leftmost col from cols (e.g., A1:Z)
    left = cols.split(":")[0]
    m = re.match(r"([A-Za-z]+)(\d+)", left)
    if not m:
        # fallback: assume A1
        base_col_letter, base_row = "A", 1
    else:
        base_col_letter, base_row = m.group(1), int(m.group(2))

    base_col_idx = col_letter_to_index(base_col_letter)
    target_col_letter = index_to_col_letter(base_col_idx + col_idx_1based - 1)
    target_row = base_row + row_idx_1based - 1
    return f"{sheet_name+'!' if sheet_name else ''}{target_col_letter}{target_row}"

def export_doc_as_text(drive_service, doc_id: str) -> str:
    """Export a Google Doc as text/plain and return the text content."""
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/plain")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8", errors="replace")

def export_doc_as_html(drive_service, doc_id: str) -> str:
    """Export a Google Doc as text/html and return the HTML content."""
    request = drive_service.files().export_media(fileId=doc_id, mimeType="text/html")
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read().decode("utf-8", errors="replace")


def get_file_metadata(drive_service, file_id: str) -> Dict:
    return drive_service.files().get(fileId=file_id, fields="id, name, mimeType").execute()

def export_doc_as_pdf_bytes(drive_service, doc_id: str) -> Tuple[bytes, str]:
    """Download/export file from Google Drive as PDF-compatible attachment.
    - If it's a Google Docs Editors file → export as PDF.
    - If it's a non-Google file (PDF, Word, etc.) → download directly.
    """
    meta = get_file_metadata(drive_service, doc_id)
    mimeType = meta.get("mimeType", "")
    name = meta.get("name", "Attachment")

    buf = io.BytesIO()

    if mimeType.startswith("application/vnd.google-apps"):
        # Native Google Doc/Sheet/Slide → export as PDF
        request = drive_service.files().export_media(fileId=doc_id, mimeType="application/pdf")
    else:
        # Non-Google file (PDF, DOCX, etc.) → direct download
        request = drive_service.files().get_media(fileId=doc_id)

    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    buf.seek(0)

    # Ensure filename ends in .pdf if exporting
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"

    return buf.read(), name


# ---------------- TEMPLATE PARSING & SUBSTITUTION ----------------

PLACEHOLDER_RE = re.compile(r"{{\s*([^}]+?)\s*}}")

def split_subject_and_body(template_text: str) -> Tuple[Optional[str], str]:
    """
    Find the first line that starts with 'Subject:' (case-insensitive).
    Return (subject_template or None, body_text_without_subject_line).
    """
    lines = template_text.splitlines()
    subject_idx = None
    subject_template = None
    for i, line in enumerate(lines):
        # Handle BOM (\ufeff) or stray spaces
        cleaned = line.lstrip("\ufeff").strip()
        if cleaned.lower().startswith("subject:"):
            subject_template = cleaned.split(":", 1)[1].strip()
            subject_idx = i
            break
    if subject_idx is not None:
        body = "\n".join(lines[subject_idx + 1:]).lstrip("\n")
    else:
        body = template_text
    return subject_template, body


def substitute_placeholders(text: str, row_dict: Dict[str, str], *, warn_subject_blanks: bool = False, context: str = "") -> Tuple[str, List[str], List[str]]:
    """
    Replace {{ColumnName}} using row_dict.
    - If ColumnName missing in row_dict -> record an error.
    - If present but value blank:
        - In body: replace with empty string
        - In subject (warn_subject_blanks=True): record a warning
    Returns (substituted_text, warnings, errors).
    """
    warnings = []
    errors = []

    def repl(m):
        key = m.group(1)
        key_stripped = key.strip()
        if key_stripped not in row_dict:
            errors.append(f"Missing column for placeholder {{ {key_stripped} }} in {context}")
            return m.group(0)  # leave as-is to visualize problem
        val = row_dict.get(key_stripped, "")
        if warn_subject_blanks and (val is None or str(val).strip() == ""):
            warnings.append(f"Blank subject value for placeholder {{ {key_stripped} }} in {context}")
            return ""
        return "" if val is None else str(val)

    return PLACEHOLDER_RE.sub(repl, text), warnings, errors

# ---------------- EMAIL SENDING ----------------

def build_email(to_email: str, subject: str, body: str, attachments: List[Tuple[bytes, str]], *, body_as_html: bool) -> bytes:
    if attachments:
        msg = MIMEMultipart()
        msg["To"] = to_email
        msg["Subject"] = subject
        # body part
        if body_as_html:
            msg.attach(MIMEText(body, "html"))
        else:
            msg.attach(MIMEText(body, "plain"))
        # attachments
        for data, fname in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            msg.attach(part)
        return msg.as_bytes()
    else:
        # simple text or html
        if body_as_html:
            msg = MIMEText(body, "html")
        else:
            msg = MIMEText(body, "plain")
        msg["To"] = to_email
        msg["Subject"] = subject
        return msg.as_bytes()

def gmail_send(gmail_service, raw_bytes: bytes):
    raw = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    return gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

# ---------------- MAIN ----------------
print(">>> Running updated email_merge_v1.py")

def main():
    parser = argparse.ArgumentParser(description="Email merge V1: Google Sheets + Google Doc template + optional Doc attachments (PDF) + Gmail send.")
    parser.add_argument("--credentials", default=DEFAULT_CREDENTIALS_FILE, help="Path to OAuth client credentials JSON (default: credentials.json)")
    parser.add_argument("--token", default=TOKEN_FILE, help="Path to store OAuth token JSON (default: token.json)")

    parser.add_argument("--sheet-id", required=True, help="Google Sheet ID")
    parser.add_argument("--range", required=True, help='A1 range, e.g., "Sheet1!A1:Z" (header row must be first row)')
    parser.add_argument("--to-col", required=True, help="Column header name that contains recipient email address")
    parser.add_argument("--selector-col", required=True, help="Column header name used to mark rows to send (e.g., 'Send?')")

    # Template source: Doc ID
    parser.add_argument("--template-doc-id", required=True, help="Google Doc ID for the email template (contains 'Subject:' on first line)")

    # Up to 3 attachment columns (each cell contains a Doc link)
    parser.add_argument("--att-col", action="append", default=[], help="Attachment column name (cell should contain a Google Doc link). Can be specified up to 3 times.")

    # Modes and testing
    parser.add_argument("--mode", choices=["test", "final"], default="test", help="Send mode: test or final (default: test)")
    parser.add_argument("--test-to", help="Email address to receive test emails (required if mode=test)")
    parser.add_argument("--only-row", type=int, help="Only process a single row (1-based index as seen in the sheet; header is row 1).")

    parser.add_argument("--body-as-html", action="store_true", help="Send email body as HTML (template should contain HTML)")
    parser.add_argument("--rate-sleep", type=float, default=0.0, help="Seconds to sleep between sends to avoid rate limits (default 0)")

    args = parser.parse_args()

    if args.mode == "test" and not args.test_to:
        parser.error("--test-to is required when --mode test")

    # Force HTML sending
    args.body_as_html = True

    # Auth
    creds = get_credentials(args.credentials, args.token)
    sheets_service = build("sheets", "v4", credentials=creds)
    drive_service = build("drive", "v3", credentials=creds)
    gmail_service = build("gmail", "v1", credentials=creds)

    # Load sheet
    headers, data_rows = load_sheet_rows(sheets_service, args.sheet_id, args.range)

    # Build a mapping from header -> column index
    header_to_idx = {h: i for i, h in enumerate(headers)}
    for needed in [args.to_col, args.selector_col]:
        if needed not in header_to_idx:
            raise RuntimeError(f"Required column '{needed}' not found in headers: {headers}")

    for att_col in args.att_col:
        if att_col and att_col not in header_to_idx:
            warn(f"Attachment column '{att_col}' not in headers; it will be ignored.")

    # First, export as plain text just to extract the subject
    try:
        plain_text = export_doc_as_text(drive_service, args.template_doc_id)
    except HttpError as e:
        error(f"Failed to export template Doc as text for subject: {e}")
        sys.exit(2)

    subject_template, _ = split_subject_and_body(plain_text)
    if not subject_template:
        warn("No 'Subject:' line found in the template Doc; subject will be empty unless you set it later.")

    # Then, export as HTML for the actual body
    try:
        body_template = export_doc_as_html(drive_service, args.template_doc_id)


        # DEBUG: After: body_template = export_doc_as_html(drive_service, args.template_doc_id)
        with open("debug_template_raw.html", "w", encoding="utf-8") as f:
            f.write(body_template)

        # DEBUG" Also save the plain-text export you already did for subject extraction:
        with open("debug_template_plain.txt", "w", encoding="utf-8") as f:
            f.write(plain_text)


        # 1) Remove all <style> blocks (Google Doc page CSS)
        body_template = re.sub(
            r'<style.*?>.*?</style>',
            '',
            body_template,
            flags=re.DOTALL | re.IGNORECASE
        )

        # 2) Remove the first "Subject:" line if it slipped into the HTML export
        #    Covers <p>, <div>, <span>, <h1>-<h6>, nested or with attributes.
        body_template = re.sub(
            r'(?is)<(p|div|span|h[1-6])[^>]*>\s*Subject:\s.*?</\1\s*>',
            '',
            body_template,
            count=1
        )

        # 2b) Also remove "Subject:" if wrapped in nested tags (e.g., <div><p>Subject:...</p></div>)
        body_template = re.sub(
            r'(?is)<div[^>]*>[\s\n\r]*<p[^>]*>\s*Subject:\s.*?</p>[\s\n\r]*</div>',
            '',
            body_template,
            count=1
        )

        # 2c) Final fallback — plain text or stray Subject: anywhere near top of body
        body_template = re.sub(
            r'(?im)^\s*Subject:\s.*?(\r?\n|<br>|</p>|</div>|</h[1-6]>|$)',
            '',
            body_template,
            count=1
        )

        # 3) Strip layout styles ONLY from the <body> tag (leave paragraph/list styles intact)
        def _clean_body_style(m):
            attrs = m.group(1) or ""
            style = m.group(2) or ""
            cleaned = re.sub(
                r'(?:\bmargin(?:-(?:left|right|top|bottom))?|\bpadding(?:-(?:left|right|top|bottom))?|\bmax-width|\bwidth)\s*:\s*[^;"]*;?',
                '',
                style,
                flags=re.IGNORECASE
            )
            # collapse duplicate semicolons/whitespace and trim
            cleaned = re.sub(r';\s*;', ';', cleaned).strip().strip(';')
            return f'<body{attrs} style="{cleaned}">' if cleaned else f'<body{attrs}>'

        body_template = re.sub(
            r'<body([^>]*)\sstyle="([^"]*)">',
            _clean_body_style,
            body_template,
            count=1,
            flags=re.IGNORECASE
        )

        # Debug: show body tag and first 300 chars
        body_open = re.search(r'<body[^>]*>', body_template, flags=re.IGNORECASE)
        debug(f"BODY TAG AFTER CLEAN: {body_open.group(0) if body_open else '(no <body> tag??)'}")
        snippet = body_template[:300].replace("\n", " ")
        debug(f"AFTER cleanup snippet (300/{len(body_template)} chars): {snippet}")

    except HttpError as e:
        error(f"Failed to export template Doc as HTML for body: {e}")
        sys.exit(2)



    # Always send HTML when using HTML body
    if not args.body_as_html:
        info("Forcing --body-as-html because template is HTML")
        args.body_as_html = True



    total = sent = skipped = errors_count = 0
    # Determine the row 1-based offset for first data row relative to the sheet A1 range.
    # Row 1 is header. So the first data row corresponds to visible row index 2 in the provided range's sheet.
    base_visible_row_index = 2

    for r_index, row in enumerate(data_rows, start=1):  # r_index is 1-based within data_rows
        total += 1

        # If --only-row is set, skip everything except that visible row number
        visible_row_number = base_visible_row_index + r_index - 1
        if args.only_row is not None and visible_row_number != args.only_row:
            continue

        # Build row dict using headers (missing values -> empty string)
        row_dict = {h: (row[i] if i < len(row) else "") for h, i in header_to_idx.items()}

        # Selector column check
        sel_val = (row_dict.get(args.selector_col, "") or "").strip()
        if not sel_val:
            skipped += 1
            info(f"Row {visible_row_number}: selector empty -> SKIP")
            continue

        if re.match(r"^\d{4}-\d{2}-\d{2}", sel_val) or sel_val.lower().startswith("test sent"):
            skipped += 1
            info(f"Row {visible_row_number}: already sent/stamped '{sel_val}' -> SKIP")
            continue

        if sel_val.upper() not in {"Y", "READY"}:
            skipped += 1
            info(f"Row {visible_row_number}: selector='{sel_val}' not Y/READY -> SKIP")
            continue

        # Recipient
        to_email = (args.test_to if args.mode == "test" else row_dict.get(args.to_col, "")).strip()
        if not to_email:
            errors_count += 1
            error(f"Row {visible_row_number}: Missing recipient email (col '{args.to_col}')")
            continue

        # Subject & Body substitution
        subject = subject_template or ""
        subj_warnings = []
        if subject:
            subject, subj_warnings, subj_errors = substitute_placeholders(subject, row_dict, warn_subject_blanks=True, context=f"row {visible_row_number} subject")
            if subj_errors:
                for e in subj_errors:
                    error(e)
                errors_count += 1
                info(f"Row {visible_row_number}: subject substitution errors -> SKIP")
                continue

        body = body_template or ""
        body, body_warnings, body_errors = substitute_placeholders(body, row_dict, warn_subject_blanks=False, context=f"row {visible_row_number} body")
        if body_errors:
            for e in body_errors:
                error(e)
            errors_count += 1
            info(f"Row {visible_row_number}: body substitution errors -> SKIP")
            continue

        for w in subj_warnings:
            warn(f"Row {visible_row_number}: {w}")

        # Attachments
        attachments: List[Tuple[bytes, str]] = []
        for att_col in args.att_col:
            if not att_col or att_col not in header_to_idx:
                continue
            doc_link = row_dict.get(att_col, "").strip()
            if not doc_link:
                continue
            doc_id = extract_doc_id_from_url(doc_link) or doc_link.strip()
            try:
                data, fname = export_doc_as_pdf_bytes(drive_service, doc_id)
                attachments.append((data, fname))
                info(f"Row {visible_row_number}: attaching {fname} (from column '{att_col}')")
            except HttpError as e:
                warn(f"Row {visible_row_number}: failed to export attachment from '{att_col}' -> {e}")

        # Build and send
        raw_bytes = build_email(to_email, subject, body, attachments, body_as_html=args.body_as_html)
        try:
            gmail_send(gmail_service, raw_bytes)
            sent += 1
            info(f"Row {visible_row_number}: SENT to {to_email} | Subject: {subject!r}")
        except HttpError as e:
            errors_count += 1
            error(f"Row {visible_row_number}: Gmail send failed -> {e}")
            continue

        # Mark the selector cell
        stamp = (f"TEST SENT {now_stamp()}" if args.mode == "test" else now_stamp())
        # Find selector column index (0-based), compute cell A1, then update
        sel_col_idx0 = header_to_idx[args.selector_col]
        sel_col_idx1 = sel_col_idx0 + 1  # 1-based
        # within data_rows, r_index is 1 for first data row; visible row number known
        cell_a1 = a1_for_cell(args.range, visible_row_number, sel_col_idx1)
        try:
            update_sheet_cell(sheets_service, args.sheet_id, cell_a1, stamp)
        except HttpError as e:
            warn(f"Row {visible_row_number}: failed to write stamp to sheet -> {e}")

        # Rate sleep if requested
        if args.rate_sleep > 0:
            import time
            time.sleep(args.rate_sleep)

    # Summary
    info("---- SUMMARY ----")
    info(f"Processed: {total}")
    info(f"Sent:      {sent}")
    info(f"Skipped:   {skipped}")
    info(f"Errors:    {errors_count}")
    info("Done.")

if __name__ == "__main__":
    main()
