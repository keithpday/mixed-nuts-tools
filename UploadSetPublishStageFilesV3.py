#!/usr/bin/env python3
"""
📦 Mixed Nuts Set Preparer & Google Drive Publisher (V3-Debug)

This program:
• Clears a local working folder to prep for publishing.
• Prompts you to select a local folder of PDF files.
• Adds watermarks (Set ID + Sequence) to each file.
• Renames and uploads PDFs to the correct Google Drive folder.
• Removes duplicates and outdated TOC files on Drive.
• Automatically generates and uploads a Set List PDF (TOC).
• Optionally launches 'newMakeBookV3.py' for next-stage processing.

══════════════════════════════════════════════════════════════════
"""

import os
import sys
import datetime
import shutil
import re
import subprocess
from tkinter import filedialog, Tk
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from PyPDF2 import PdfReader, PdfWriter


# === Banner ===
def show_banner():
    banner = """
══════════════════════════════════════════════════════════════════
📦 Mixed Nuts Set Preparer & Google Drive Publisher (Debug Build)
══════════════════════════════════════════════════════════════════
"""
    print(banner)


# === Google Drive Authentication ===
CREDENTIALS_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
TOKEN_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/token_drive.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

creds = None
if os.path.exists(TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
    with open(TOKEN_FILE, "w") as token:
        token.write(creds.to_json())

drive_service = build("drive", "v3", credentials=creds)


# === Step 1: Clear SetPublishDump ===
dump_folder = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/data/SetPublishDump")

def clear_dump_folder():
    if not os.path.exists(dump_folder):
        os.makedirs(dump_folder)
    for f in os.listdir(dump_folder):
        try:
            os.remove(os.path.join(dump_folder, f))
        except Exception as e:
            print(f"⚠️  Could not remove {f}: {e}")

clear_dump_folder()


# === Step 2: Folder selection ===
default_folder = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/data/SetPublishStage")
root = Tk()
root.withdraw()
show_banner()

folder_path = filedialog.askdirectory(initialdir=default_folder, title="Select Folder")
if not folder_path:
    print("❌ No folder selected. Exiting.")
    sys.exit(1)

print(f"📂 Selected local folder: {folder_path}")
print(f"📄 Local files found: {len(os.listdir(folder_path))}")


# === Step 3: Prompt for folder name and ID ===
google_docs_folder_name = input("Enter the Google Docs Set Folder Name (i.e. 01 Set, Halloween Set): ").strip()
set_id = input("Enter the Set ID (e.g., 01, T3B, A2, Halloween): ").strip()

if re.match(r'^[A-Z0-9]+$', set_id, re.IGNORECASE):
    set_id = set_id.capitalize()  # preserve readable casing (e.g., Halloween)
if not re.match(r'^[A-Za-z0-9 ]+$', set_id):
    print("⚠ Invalid Set ID format. Exiting.")
    sys.exit(1)

default_revision_date = datetime.date.today().strftime("%Y.%m.%d")
revision_date = input(f"Enter the Revision Date (default: {default_revision_date}): ").strip() or default_revision_date


# === Step 4: Smart folder finder ===
def get_drive_folder_id(folder_name, parent_id=None, create_if_missing=False):
    """Find a Google Drive folder (case-insensitive), optionally under a specific parent."""
    if not folder_name:
        return None

    query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    page_token = None
    folders = []

    while True:
        response = drive_service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, parents)",
            pageToken=page_token,
            pageSize=100  # ✅ ensure all results per page
        ).execute()

        folders.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    candidates = [f for f in folders if f["name"].strip().lower() == folder_name.strip().lower()]

    if not candidates:
        if create_if_missing:
            confirm = input(f"⚠ Folder '{folder_name}' not found. Create it? (y/n): ").strip().lower()
            if confirm == "y":
                metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
                if parent_id:
                    metadata["parents"] = [parent_id]
                folder = drive_service.files().create(body=metadata, fields="id").execute()
                print(f"📁 Created new Google Drive folder: {folder_name}")
                return folder["id"]
            else:
                print("❌ Folder creation cancelled. Exiting.")
                sys.exit(1)
        else:
            print(f"⚠ Folder '{folder_name}' not found.")
            return None

    if parent_id:
        for f in candidates:
            if "parents" in f and parent_id in f["parents"]:
                print(f"📁 Found folder under correct parent: {f['name']}")
                return f["id"]
        print(f"⚠ Folder '{folder_name}' found, but not under the expected parent. Using first match anyway.")
        return candidates[0]["id"]

    print(f"📁 Found existing Google Drive folder: {candidates[0]['name']}")
    return candidates[0]["id"]


# === Step 4.5: Resolve folder hierarchy ===
print("\n📋 Searching for folders (safe mode, paginated):")
page_token = None
all_folders = []
page = 1
max_pages = 10  # safeguard against runaway pagination

while True:
    try:
        resp = drive_service.files().list(
            q="mimeType='application/vnd.google-apps.folder' and trashed=false",
            fields="nextPageToken, files(id, name, parents)",
            pageToken=page_token,
            pageSize=100
        ).execute()
    except Exception as e:
        print(f"⚠️  Drive API error on page {page}: {e}")
        break

    batch = resp.get("files", [])
    if not batch:
        print(f"⚠️  No folders returned on page {page}. Stopping early.")
        break

    print(f"📄 Retrieved {len(batch)} folders on page {page}")
    all_folders.extend(batch)

    page_token = resp.get("nextPageToken")
    if not page_token or page >= max_pages:
        break
    page += 1

print(f"📋 Total folders gathered: {len(all_folders)}")

if not all_folders:
    print("⚠️  No folders retrieved from Drive. Check credentials or quota.")
else:
    for f in all_folders:
        if "AA Numbered Sets" in f["name"] or "Halloween" in f["name"]:
            print(f"   {f['name']}  →  id={f['id']}  parents={f.get('parents')}")


# === Step 4.6: Resolve folder chain (fast lookup) ===
def quick_find(folder_name, parent_name=None):
    """Fast lookup using the already fetched all_folders list."""
    matches = [f for f in all_folders if f["name"].strip().lower() == folder_name.strip().lower()]
    if parent_name:
        parent_candidates = [f["id"] for f in all_folders if f["name"].strip().lower() == parent_name.strip().lower()]
        for f in matches:
            if "parents" in f and any(pid in f["parents"] for pid in parent_candidates):
                return f["id"]
    return matches[0]["id"] if matches else None

parent_folder_id = quick_find("AA Numbered Sets, Books, and Recordings")
intermediate_name = google_docs_folder_name.replace(" Set", "").strip()
intermediate_id = quick_find(intermediate_name, "AA Numbered Sets, Books, and Recordings")
set_folder_id = quick_find(google_docs_folder_name, intermediate_name)

print(f"🔍 parent_folder_id = {parent_folder_id}")
print(f"🔍 intermediate_id = {intermediate_id} ({intermediate_name})")
print(f"🔍 set_folder_id = {set_folder_id}")

if not parent_folder_id or not intermediate_id or not set_folder_id:
    print("❌ Could not locate one or more required folders. Exiting.")
    sys.exit(1)



# === Step 5: Helpers ===
def escape_drive_query_string(name):
    return re.sub(r"[\'\(\)]", "", name)

def remove_existing_files(name, folder_id):
    query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    files = drive_service.files().list(q=query, fields="files(id,name)").execute().get("files", [])
    for f in files:
        print(f"🗑 Trashing existing file: {f['name']}")
        drive_service.files().update(fileId=f["id"], body={"trashed": True}).execute()

def remove_old_toc_files(folder_id, set_id):
    query = f"name contains '{set_id}-00' and '{folder_id}' in parents and trashed=false"
    files = drive_service.files().list(q=query, fields="files(id,name)").execute().get("files", [])
    if not files:
        print(f"ℹ No old TOC files found for set '{set_id}'.")
        return
    for f in files:
        print(f"🗑 Removing old TOC: {f['name']}")
        drive_service.files().update(fileId=f["id"], body={"trashed": True}).execute()


# === Step 6: Watermark ===
def add_watermark(in_path, out_path, text):
    reader = PdfReader(in_path)
    writer = PdfWriter()
    width, height = letter
    wm_path = os.path.join(dump_folder, "temp_wm.pdf")

    c = canvas.Canvas(wm_path, pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    x = width - c.stringWidth(text, "Helvetica-Bold", 14) - 20
    c.drawString(x, height - 20, text)
    c.save()

    wm = PdfReader(wm_path).pages[0]
    for p in reader.pages:
        p.merge_page(wm)
        writer.add_page(p)

    with open(out_path, "wb") as f:
        writer.write(f)
    os.remove(wm_path)


# === Step 7: Create TOC PDF ===
def create_toc_pdf(path, title, date, files):
    print(f"📝 Building TOC: {len(files)} entries")
    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, h - 50, title)
    c.setFont("Helvetica", 12)
    c.drawString(100, h - 70, f"Revision Date: {date}")
    c.line(100, h - 80, 500, h - 80)

    y = h - 100
    c.setFont("Helvetica", 10)
    for f in sorted(files):
        if "narration" not in f.lower():
            if y < 50:
                c.showPage()
                y = h - 50
                c.setFont("Helvetica", 10)
            c.drawString(100, y, f)
            y -= 15

    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.gray)
    c.drawString(100, 30, "Generated by Mixed Nuts Set Publisher")
    c.save()


# === Step 8: Process PDFs ===
if not os.listdir(folder_path):
    print("ℹ No local PDFs found in folder.")
else:
    for f in os.listdir(folder_path):
        p = os.path.join(folder_path, f)
        if not os.path.isfile(p):
            print(f"⤴️  Skipping non-file: {f}")
            continue
        seq = input(f"\nEnter sequence ID for {f}: ").strip()
        if not re.match(r"^\d{2}$", seq):
            seq = f"0{seq}"
        newname = f"{set_id}-{seq} {f}"
        print(f"📄 Processing: {newname}")

        remove_existing_files(newname, set_folder_id)
        stamped = os.path.join(dump_folder, f"stamped_{newname}")
        add_watermark(p, stamped, f"{set_id}-{seq}")
        final = os.path.join(dump_folder, newname)
        shutil.move(stamped, final)

        media = MediaFileUpload(final, resumable=True)
        drive_service.files().create(body={"name": newname, "parents": [set_folder_id]}, media_body=media).execute()
        print(f"✅ Uploaded: {newname}")


# === Step 9: TOC Regeneration ===
print("\n📄 Checking for Set List (TOC) update...")
regen = input("Regenerate Set List PDF even if no new files were uploaded? (y/n): ").strip().lower()

if regen == "y" or any(os.listdir(folder_path)):
    print("\n📄 Generating Set List PDF (TOC)...")
    remove_old_toc_files(set_folder_id, set_id)

    query = f"'{set_folder_id}' in parents and trashed=false"
    response = drive_service.files().list(q=query, fields="files(name)").execute()
    drive_names = [f["name"] for f in response.get("files", [])]

    prefix = (set_id + "-").lower()
    all_drive_files = [n for n in drive_names if n.lower().startswith(prefix)]
    print(f"🔎 Drive files matching '{set_id}-': {len(all_drive_files)}")

    toc_name = f"{set_id}-00 Set List {revision_date}.pdf"
    toc_path = os.path.join(dump_folder, toc_name)
    create_toc_pdf(toc_path, google_docs_folder_name, revision_date, all_drive_files)

    media = MediaFileUpload(toc_path, resumable=True)
    drive_service.files().create(body={"name": toc_name, "parents": [set_folder_id]}, media_body=media).execute()
    print(f"✅ Uploaded Set List PDF: {toc_name}")
else:
    print("ℹ Skipping Set List PDF regeneration per user choice.")

print("\nProcess complete!")

# === Step 10: Optional next stage ===
resp = input("Run newMakeBookV3.py? (y/n): ").strip().lower()
if resp == "y":
    subprocess.Popen(["python3", "-m", "idlelib", "-r", "newMakeBookV3.py"])
else:
    print("newMakeBookV3.py was not run.")
