from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from oauth2client import file, client, tools
import sys
import re

def authenticate_drive():
    """Authenticate and return a Google Drive service object."""
    SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    
    # Authenticate and build the Google Drive API service
    store = file.Storage(SERVICE_ACCOUNT_FILE)
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
        creds = tools.run_flow(flow, store)
    
    return build("drive", "v3", credentials=creds)

def get_folder_id(service, folder_name):
    """Retrieve the folder ID based on the folder name."""
    try:
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        folders = results.get("files", [])
        
        if not folders:
            print(f"No folder found with name: {folder_name}")
            return None
        
        return folders[0]["id"]
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def get_files_in_folder(service, folder_id):
    """Retrieve all files in the specified folder, handling pagination."""
    files = []
    page_token = None

    while True:
        try:
            query = f"'{folder_id}' in parents and trashed = false"
            results = service.files().list(
                q=query,
                fields="nextPageToken, files(id, name)",
                pageSize=100,
                pageToken=page_token
            ).execute()

            files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")

            if not page_token:
                break  # No more pages

        except HttpError as error:
            print(f"An error occurred: {error}")
            break

    return files

def rename_files(service, files, search_str, replace_str):
    """Rename files that contain the search string, case insensitive."""
    pattern = re.compile(re.escape(search_str), re.IGNORECASE)  # Case-insensitive match

    for file in files:
        old_name = file["name"]
        if pattern.search(old_name):  # Match ignoring case
            new_name = pattern.sub(replace_str, old_name)
            try:
                service.files().update(
                    fileId=file["id"],
                    body={"name": new_name}
                ).execute()
                print(f"Renamed: {old_name} -> {new_name}")
            except HttpError as error:
                print(f"Failed to rename {old_name}: {error}")

def main():
    service = authenticate_drive()
    folder_name = input("Enter the folder name: ")
    search_str = input("Enter the search string: ")
    replace_str = input("Enter the replacement string: ")
    
    folder_id = get_folder_id(service, folder_name)
    if not folder_id:
        return
    
    files = get_files_in_folder(service, folder_id)
    rename_files(service, files, search_str, replace_str)

if __name__ == "__main__":
    main()
