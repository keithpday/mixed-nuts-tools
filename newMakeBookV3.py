import os
import sys
from PyPDF2 import PdfMerger
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from io import BytesIO
import time

# === Google Drive Authentication ===
CREDENTIALS_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
TOKEN_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/token_drive.json")  # shared Drive token
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

# === Helpers ===
def get_drive_folder_id(folder_name, parent_id=None):
    query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    response = drive_service.files().list(q=query, fields="files(id)").execute()
    folders = response.get("files", [])
    if folders:
        return folders[0]["id"]
    metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    print(f"📂 Created Google Drive folder: {folder_name}")
    return folder["id"]

def remove_existing_file(file_name, folder_id):
    query = f"name = '{file_name}' and '{folder_id}' in parents and trashed = false"
    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    for file in response.get("files", []):
        print(f"🗑 Removing existing file: {file['name']}")
        drive_service.files().delete(fileId=file["id"]).execute()

def list_pdfs_in_folder(folder_id):
    query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed = false"
    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return sorted(response.get("files", []), key=lambda x: x["name"])

def download_pdf(file_id):
    request = drive_service.files().get_media(fileId=file_id)
    file_bytes = BytesIO()
    downloader = MediaIoBaseDownload(file_bytes, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    file_bytes.seek(0)
    return file_bytes

# === Step 1: User Prompts ===
set_name = input("Enter the source Set folder (i.e. Set A, 01 Set): ").strip()
book_folder = input("Enter the Book parent folder (i.e. 01, AA Music Books): ").strip() 

new_book_name = input("Enter the new Book Name (i.e. 01 Book.pdf - must end with .pdf): ").strip()

if not new_book_name.lower().endswith(".pdf"):
    print("❌ Book name must end with '.pdf'. Exiting.")
    sys.exit(1)

# === Step 2: Locate Google Drive folders ===
set_parent_id = get_drive_folder_id(book_folder)
set_folder_id = get_drive_folder_id(set_name, parent_id=set_parent_id)

book_parent_id = get_drive_folder_id(book_folder)

if not set_folder_id:
    print(f"❌ Could not locate set folder '{set_name}'. Exiting.")
    sys.exit(1)

# === Step 3: Combine PDFs from Set Folder ===
pdf_files = list_pdfs_in_folder(set_folder_id)
if not pdf_files:
    print("❌ No PDFs found in the set folder. Exiting.")
    sys.exit(1)

print(f"📚 Combining {len(pdf_files)} PDF files from '{set_name}'...")
merger = PdfMerger()
for file in pdf_files:
    print(f"   ➕ {file['name']}")
    pdf_stream = download_pdf(file["id"])
    merger.append(pdf_stream)

# === Save merged PDF to a temporary file ===
temp_path = "combined_book_temp.pdf"
with open(temp_path, "wb") as f:
    merger.write(f)
merger.close()

# === Step 4: Upload Final Book ===
remove_existing_file(new_book_name, book_parent_id)

media = MediaFileUpload(temp_path, mimetype="application/pdf")
file_metadata = {"name": new_book_name, "parents": [book_parent_id]}
drive_service.files().create(body=file_metadata, media_body=media).execute()

print(f"✅ Uploaded new book: {new_book_name}")
# Wait a moment to ensure the file handle is released
time.sleep(0.5)

try:
    os.remove(temp_path)
    print("🧹 Cleaned up local temp file.")
except PermissionError:
    print("⚠ Warning: Could not delete the temp file. You may need to delete it manually.")
print("🧹 Cleaned up local temp file.")
print("🎉 Process complete.")
