from googleapiclient.discovery import build
from google.oauth2 import service_account
from oauth2client import file, client, tools
import sys

# Replace with your Service Account JSON file path
SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Authenticate and build the Google Drive API service
store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    creds = tools.run_flow(flow, store)
drive_service = build('drive', 'v3', credentials=creds)

def get_folder_id(folder_name):
    """
    Searches for the given folder name in Google Drive and returns its folder ID.
    """
    try:
        query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if not files:
            print(f"❌ Folder '{folder_name}' not found in Google Drive. Exiting...")
            sys.exit(1)

        folder_id = files[0]["id"]  # If multiple folders match, it picks the first one
        print(f"✔ Found Folder: {folder_name} (ID: {folder_id})")
        return folder_id

    except Exception as e:
        print(f"❌ Error finding folder: {e}")
        sys.exit(1)

def create_google_doc(folder_id, set_name, seq_id, song_title):
    """
    Creates an empty Google Doc with the given Set Name, Sequence ID, and Song Title in the target folder.
    """
    doc_title = f"{set_name}-{seq_id} ! {song_title} narration"
    
    file_metadata = {
        "name": doc_title,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [folder_id]
    }
    
    try:
        file = drive_service.files().create(body=file_metadata, fields="id").execute()
        print(f"✔ Created: {doc_title} (Doc ID: {file.get('id')})")
    except Exception as e:
        print(f"❌ Error creating document: {e}")

if __name__ == "__main__":
    print("Google Docs Creator - Enter Folder Name, Set Name, then Sequence ID & Song Title (Ctrl+C to Exit)\n")

    # Get the folder name and find its ID
    folder_name = input("Enter Google Drive Folder Name: ").strip()
    folder_id = get_folder_id(folder_name)

    # Get the Set Name once
    set_name = input("Enter Set Name: ").strip()
    if not set_name:
        print("Set Name cannot be empty. Exiting...")
        sys.exit(1)

    print(f"\nCreating narrations for set: {set_name} in folder: {folder_name}\n")

    try:
        while True:
            seq_id = input("Enter Sequence ID: ").strip()
            if not seq_id:
                print("Sequence ID cannot be empty. Try again.")
                continue

            song_title = input("Enter Song Title: ").strip()
            if not song_title:
                print("Song Title cannot be empty. Try again.")
                continue
            
            create_google_doc(folder_id, set_name, seq_id, song_title)
    
    except KeyboardInterrupt:
        print("\nProgram terminated by user. Exiting...")
        sys.exit(0)
