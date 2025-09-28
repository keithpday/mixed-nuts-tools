import os
import sys
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauth2client import file, client, tools

# === Google Drive Authentication ===
SERVICE_ACCOUNT_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/my-service-account-key.json")
SCOPES = ["https://www.googleapis.com/auth/drive"]

store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    #flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    flow = client.flow_from_clientsecrets(os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/credentials.json"), SCOPES)
    creds = tools.run_flow(flow, store)

drive_service = build('drive', 'v3', credentials=creds)

# === Banner ===
print("=" * 60)
print(" Google Docs Set File Sequencer")
print(" This program renames files in a Google Docs folder by adding a")
print(" Set ID and sequence number prefix to each file.")
print(" Example: PAT-03 America.pdf  or  01-12 Fascination.docx")
print("=" * 60)

# === Prompt for folder and Set ID ===
folder_name = input("Enter the Google Docs set folder name (e.g., '01 Recordings'): ").strip()
set_id = input("Enter the Set ID (e.g.'01'): ").strip()

if not set_id:
    print("Error: Set ID cannot be empty.")
    sys.exit(1)

# === Get folder ID ===
def get_folder_id_by_name(folder_name):
    query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = results.get('files', [])
    if not folders:
        print(f"Error: Folder '{folder_name}' not found.")
        sys.exit(1)
    if len(folders) > 1:
        print(f"Multiple folders named '{folder_name}' found:")
        for idx, folder in enumerate(folders):
            print(f"{idx + 1}. {folder['name']} (ID: {folder['id']})")
        choice = input("Select the number of the folder you want to use: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(folders)):
            print("Invalid selection.")
            sys.exit(1)
        return folders[int(choice) - 1]['id']
    return folders[0]['id']

folder_id = get_folder_id_by_name(folder_name)

# === Get files in folder ===
query = f"'{folder_id}' in parents and trashed=false"
files = drive_service.files().list(q=query, fields="files(id, name)").execute().get('files', [])

if not files:
    print("No files found in the specified folder.")
    sys.exit(0)

changes = []
skipped = []

for file in files:
    file_id = file['id']
    filename = file['name']

    # Skip if already has SetID-XX pattern
    if filename.startswith(f"{set_id}-"):
        skipped.append((filename, "Already has SetID prefix"))
        continue

    print(f"\nCurrent file: {filename}")
    seq = input("Enter sequence ID (e.g., 01 or 1): ").strip()
    if len(seq) == 1:
        seq = "0" + seq

    if not seq.isdigit() or len(seq) != 2:
        print("Invalid sequence ID. Skipping this file.")
        skipped.append((filename, "Invalid sequence input"))
        continue

    new_name = f"{set_id}-{seq} {filename}"
    try:
        drive_service.files().update(fileId=file_id, body={"name": new_name}).execute()
        print(f"Renamed to: {new_name}")
        changes.append((filename, new_name))
    except HttpError as error:
        print(f"Failed to rename '{filename}': {error}")
        skipped.append((filename, f"API error: {error}"))

# === Summary ===
print("\n" + "=" * 60)
print("Rename Summary")
print("=" * 60)

if changes:
    print("\nRenamed files:")
    for old, new in changes:
        print(f"'{old}' -> '{new}'")
else:
    print("No files renamed.")

if skipped:
    print("\nSkipped files:")
    for fname, reason in skipped:
        print(f"- {fname}: {reason}")

print("\nRun complete")
