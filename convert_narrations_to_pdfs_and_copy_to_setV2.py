import os
import io
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# === Auth ===
SERVICE_ACCOUNT_FILE = os.path.expanduser(
    "~/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json"
)
SCOPES = ["https://www.googleapis.com/auth/drive"]
creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=creds)

# === Helpers ===
def get_folder_id(folder_name):
    """Find a folder by unique name anywhere (no parent restriction)."""
    query = (
        "mimeType = 'application/vnd.google-apps.folder' and trashed = false "
        f"and name = '{folder_name}'"
    )
    res = drive_service.files().list(
        q=query,
        spaces="drive",
        fields="files(id,name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        pageSize=10,
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None

def list_google_docs(folder_id):
    query = f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.document' and trashed = false"
    results = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        pageSize=1000,
    ).execute()
    return results.get('files', [])

def delete_existing_file(folder_id, file_name):
    escaped = file_name.replace("'", "\\'")
    query = f"'{folder_id}' in parents and name = '{escaped}' and trashed = false"
    results = drive_service.files().list(
        q=query,
        fields="files(id, name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        pageSize=100,
    ).execute()
    for f in results.get("files", []):
        drive_service.files().delete(fileId=f["id"]).execute()
        print(f"🗑 Deleted existing file: {f['name']}")

def export_doc_to_pdf(file_id):
    request = drive_service.files().export_media(fileId=file_id, mimeType='application/pdf')
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    return fh

def upload_pdf(file_stream, file_name, folder_id):
    file_metadata = {'name': file_name, 'parents': [folder_id], 'mimeType': 'application/pdf'}
    media = MediaIoBaseUpload(file_stream, mimetype='application/pdf')
    drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True,
    ).execute()

def main():
    print("\nGoogle Docs → PDF (Narrations) with optional copy to Set\n")

    # --- Prompts (simplified) ---
    set_num = input("Enter the Set Number (e.g., 01): ").strip()
    default_narr = f"{set_num} Narrations"
    default_set = f"{set_num} Set"

    narrations_folder = input(f"Narrations folder [{default_narr}]: ").strip() or default_narr
    set_folder = input(f"Set destination folder [{default_set}]: ").strip() or default_set

    # --- Resolve folders by unique name ---
    narrations_folder_id = get_folder_id(narrations_folder)
    if not narrations_folder_id:
        print(f"❌ Folder not found: {narrations_folder}")
        return

    set_folder_id = get_folder_id(set_folder)
    if not set_folder_id:
        print(f"❌ Folder not found: {set_folder}")
        return

    # --- Process all Google Docs in Narrations ---
    docs = list_google_docs(narrations_folder_id)
    if not docs:
        print(f"ℹ No Google Docs found in '{narrations_folder}'.")
        return

    for doc in docs:
        doc_id = doc['id']
        doc_name = doc['name']
        pdf_name = f"{doc_name}.pdf"
        print(f"Processing '{doc_name}'...")

        pdf_stream = export_doc_to_pdf(doc_id)

        # Replace existing in narrations folder
        delete_existing_file(narrations_folder_id, pdf_name)
        upload_pdf(pdf_stream, pdf_name, narrations_folder_id)
        print(f"✅ Uploaded '{pdf_name}' to '{narrations_folder}'.")

        # Copy to Set folder
        pdf_stream.seek(0)
        delete_existing_file(set_folder_id, pdf_name)
        upload_pdf(pdf_stream, pdf_name, set_folder_id)
        print(f"📤 Copied '{pdf_name}' to '{set_folder}'.")

    print("🎉 Processing complete.")

if __name__ == "__main__":
    main()
