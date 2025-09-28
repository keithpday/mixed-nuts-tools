import os
import sys
import datetime
import shutil
import re
import urllib.parse
import subprocess
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client import file, client, tools
from tkinter import filedialog, Tk
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from PyPDF2 import PdfReader, PdfWriter

import os
import sys
...
from PyPDF2 import PdfReader, PdfWriter

def show_banner():
    banner = """
══════════════════════════════════════════════════════════════════
📦 Mixed Nuts Set Preparer & Google Drive Publisher

This program:
• Clears a local working folder to prep for publishing.
• Prompts you to select a local folder of PDF files.
• Adds watermarks (Set ID + Sequence) to each file.
• Renames and uploads PDFs to the correct Google Drive folder.
• Removes duplicates and outdated TOC files on Drive.
• Automatically generates and uploads a Set List PDF (TOC).
• Optionally launches 'newMakeBook.py' for next-stage processing.

Drive folder must exist under:
  📁 AA Numbered Sets, Books, and Recordings

Uses OAuth2 credentials and Google Drive API.
══════════════════════════════════════════════════════════════════
"""
    print(banner)


# Authenticate and build the Google Drive API service
# SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
SERVICE_ACCOUNT_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/my-service-account-key.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    #flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    flow = client.flow_from_clientsecrets(os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/credentials.json"), SCOPES)
    creds = tools.run_flow(flow, store)

drive_service = build('drive', 'v3', credentials=creds)

# Step 1: Define and Clear the SetPublishDump Folder
dump_folder = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/data/SetPublishDump")

def clear_dump_folder():
    """Clears all files from the SetPublishDump folder at the start of the process."""
    if not os.path.exists(dump_folder):
        os.makedirs(dump_folder)

    success = True
    for file_name in os.listdir(dump_folder):
        file_path = os.path.join(dump_folder, file_name)
        try:
            os.remove(file_path)
            print(f"🗑 Deleted from SetPublishDump: {file_name}")
        except PermissionError:
            print(f"⚠ Warning: Unable to delete {file_name}. It may be in use.")
            success = False

    if not success:
        print("⚠ Some files could not be deleted. You may need to manually clear them before running the script again.")

# Clear the dump folder before proceeding
clear_dump_folder()

# Step 2: Prompt user for a folder
default_folder = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/data/SetPublishStage")


root = Tk()
root.withdraw()

# ✅ Show the banner **after** Tk initializes cleanly
show_banner()

folder_path = filedialog.askdirectory(initialdir=default_folder, title="Select Folder")
if not folder_path:
    print("No folder selected. Exiting.")
    sys.exit(1)

# Step 3: Prompt for Google Docs Folder Name
google_docs_folder_name = input("Enter the Google Docs Set Folder Name (i.e. 01 Set): ").strip()

# Step 4: Prompt for 2-digit Set ID
set_id = input("Enter the Set ID (e.g., 01, T3B, A2): ").strip().upper()
if not re.match(r'^[A-Z0-9]+$', set_id):
    print("⚠ Invalid Set ID format. Use only letters and numbers (no dashes or underscores). Exiting.")
    sys.exit(1)

# Step 5: Prompt for Revision Date (in YYYY.MM.DD format)
default_revision_date = datetime.date.today().strftime("%Y.%m.%d")
revision_date = input(f"Enter the Revision Date (default: {default_revision_date}): ").strip() or default_revision_date

# Step 6: Find or Create Google Drive Folder
def get_drive_folder_id(folder_name, parent_id=None):
    """Get or create the Google Drive folder, ensuring it's not trashed."""
    if not folder_name:
        return None

    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = response.get('files', [])

    if folders:
        return folders[0]['id']

    metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
    if parent_id:
        metadata['parents'] = [parent_id]

    folder = drive_service.files().create(body=metadata, fields="id").execute()
    print(f"📂 Created new Google Drive folder: {folder_name}")

    return folder['id']

# Get the Google Drive Folder ID under "AA Numbered Sets, Books, and Recordings"
parent_folder_id = get_drive_folder_id("AA Numbered Sets, Books, and Recordings")
set_folder_id = get_drive_folder_id(google_docs_folder_name, parent_folder_id)

# Step 7: Remove Duplicate Files in Google Drive
def escape_drive_query_string(name):
    name = name.replace("'", "’")
    name = re.sub(r'[\(\)]', '', name)
    name = re.sub(r'(?<!\w)\.(?!\w)', '', name)
    return name

def remove_existing_files(file_name, folder_id):
    if not folder_id:
        return

    try:
        safe_file_name = escape_drive_query_string(file_name)
        query = f'name contains "{safe_file_name}" and "{folder_id}" in parents and trashed = false'

        response = drive_service.files().list(q=query, fields="files(id, name)").execute()
        existing_files = response.get('files', [])

        if not existing_files:
            print(f"ℹ No existing files to trash for {file_name}.")
            return

        for file in existing_files:
            print(f"🗑 Trashing existing file: {file['name']}")
            drive_service.files().update(fileId=file["id"], body={"trashed": True}).execute()

    except Exception as e:
        print(f"⚠ Error removing existing files for {file_name}: {e}")

def remove_old_toc_files(folder_id, set_id, folder_name):
    if not folder_id:
        return

    try:
        safe_folder_name = escape_drive_query_string(folder_name)
        query = f"name contains \"{set_id}-00\" and '{folder_id}' in parents and trashed = false"

        response = drive_service.files().list(q=query, fields="files(id, name)").execute()
        matching_files = response.get('files', [])

        if not matching_files:
            print(f"ℹ No TOC files found to trash in {folder_name}.")
            return

        for file in matching_files:
            print(f"\n🗑 Trashing TOC file: {file['name']}")
            drive_service.files().update(fileId=file["id"], body={"trashed": True}).execute()

    except Exception as e:
        print(f"⚠ Error trashing TOC files in {folder_name}: {e}")

# Step 8: Process Files in the Selected Folder
def add_watermark(input_pdf_path, output_pdf_path, watermark_text):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    width, height = letter
    watermark_pdf_path = os.path.join(dump_folder, "temp_watermark.pdf")

    c = canvas.Canvas(watermark_pdf_path, pagesize=letter)
    c.setFont("Helvetica-Bold", 14)
    text_width = c.stringWidth(watermark_text, "Helvetica-Bold", 14)
    x_position = width - text_width - 20
    y_position = height - 20

    c.drawString(x_position, y_position, watermark_text)
    c.save()

    watermark_reader = PdfReader(watermark_pdf_path)
    watermark_page = watermark_reader.pages[0]

    for page in reader.pages:
        page.merge_page(watermark_page)
        writer.add_page(page)

    with open(output_pdf_path, "wb") as output_pdf:
        writer.write(output_pdf)

    os.remove(watermark_pdf_path)

# Process each file
for file_name in os.listdir(folder_path):
    file_path = os.path.join(folder_path, file_name)
    ### print("File path to be processed: ", file_path)

    if os.path.isfile(file_path):
        sequence_id = input(f"\nEnter sequence ID for {file_name}: ").strip()
        if not re.match(r'^\d{2}$', sequence_id):
            sequence_id = f"0{sequence_id}"

        new_file_name = f"{set_id}-{sequence_id} {file_name}"
        print(f"📄 Processing file: {new_file_name}")

        remove_existing_files(new_file_name, set_folder_id)
        shutil.copy(file_path, os.path.join(dump_folder, new_file_name))

        stamped_file_path = os.path.join(dump_folder, f"stamped_{new_file_name}")
        print(f"🎨 Adding watermark: {set_id}-{sequence_id}")
        add_watermark(file_path, stamped_file_path, f"{set_id}-{sequence_id}")

        final_uploaded_file_path = os.path.join(dump_folder, new_file_name)

        shutil.move(stamped_file_path, final_uploaded_file_path)

        media = MediaFileUpload(final_uploaded_file_path, resumable=True)
        drive_service.files().create(body={'name': new_file_name, 'parents': [set_folder_id]}, media_body=media).execute()
        print(f"✅ Successfully uploaded: {new_file_name}")

# Step 9: Generate and Upload TOC
safe_folder_name = escape_drive_query_string(google_docs_folder_name)
remove_old_toc_files(set_folder_id, set_id, safe_folder_name)

query = f"name contains \"{set_id}-\" and '{set_folder_id}' in parents and trashed = false"
response = drive_service.files().list(q=query, fields="files(name)").execute()
all_drive_files = [file['name'] for file in response.get('files', [])]

toc_file_name = f"{set_id}-00 Set List {revision_date}.pdf"
toc_file_path = os.path.join(dump_folder, toc_file_name)

def create_toc_pdf(file_path, title, date, file_list):
    print(f"\n📄 Processing set list file.")
    c = canvas.Canvas(file_path, pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, height - 50, title)
    c.setFont("Helvetica", 12)
    c.drawString(100, height - 70, f"Revision Date: {date}")
    c.line(100, height - 80, 500, height - 80)

    y_position = height - 100
    c.setFont("Helvetica", 10)

    for file in sorted(file_list):
        if "narration" not in file.lower():
            if date in file:
                c.setFillColor(colors.red)
            else:
                c.setFillColor(colors.black)

            if y_position < 50:
                c.showPage()
                y_position = height - 50
                c.setFont("Helvetica", 10)

            c.drawString(100, y_position, file)
            y_position -= 15

    c.save()

create_toc_pdf(toc_file_path, google_docs_folder_name, revision_date, all_drive_files)

media = MediaFileUpload(toc_file_path, resumable=True)
drive_service.files().create(body={'name': toc_file_name, 'parents': [set_folder_id]}, media_body=media).execute()
print(f"✅ Successfully uploaded set list file")

print("\nProcess complete!")

# Prompt to run newMakeBook.py only if everything succeeded
response = input("Run newMakeBook.py? (y/n): ").strip().lower()
if response == 'y':
    # subprocess.Popen(["pythonw", "-m", "idlelib", "-r", "newMakeBook.py"])
    subprocess.Popen(["python3", "-m", "idlelib", "-r", "newMakeBook.py"])
else:
    print("newMakeBook.py was not run.")
