import os
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# -----------------------------
# 🔐 Authentication Setup
# -----------------------------

# Define the scope
SCOPES = ['https://www.googleapis.com/auth/drive']

# Path to your service account key file
SERVICE_ACCOUNT_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/spatial-edition-458414-t9-3d59add520ba.json")

# Authenticate and construct service
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# -----------------------------
# 📂 Helper Functions
# -----------------------------
def get_all_subfolder_ids(parent_id):
    """Recursively retrieves all subfolder IDs under the given parent folder."""
    subfolder_ids = []
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(
        q=query,
        fields="files(id)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    folders = results.get('files', [])
    for folder in folders:
        folder_id = folder['id']
        subfolder_ids.append(folder_id)
        # Recursively get subfolders
        subfolder_ids.extend(get_all_subfolder_ids(folder_id))
    return subfolder_ids

def search_mp3_files_in_folders(song_name, folder_ids):
    """Searches for MP3 files matching the song name in the specified folders."""
    matching_files = []
    for folder_id in folder_ids:
        # Escape single quotes in song_name
        escaped_song_name = song_name.replace("'", "\\'")
        query = f"'{folder_id}' in parents and name = '{escaped_song_name}.mp3' and mimeType = 'audio/mpeg' and trashed = false"
        results = drive_service.files().list(
            q=query,
            fields='files(id, name)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        items = results.get('files', [])
        matching_files.extend(items)
    return matching_files

def get_folder_id(folder_name):
    """Retrieve the folder ID for the given folder name."""
    try:
        query = f"name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            pageSize=1
        ).execute()
        folders = results.get('files', [])
        if not folders:
            print(f"❌ Folder '{folder_name}' not found.")
            return None
        return folders[0]['id']
    except HttpError as error:
        print(f"An error occurred: {error}")
        return None

def list_files_in_folder(folder_id):
    """List all files in the specified folder."""
    try:
        query = f"'{folder_id}' in parents and trashed = false"
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, mimeType)',
            pageSize=1000
        ).execute()
        items = results.get('files', [])
        return items
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []

def search_mp3_files(song_name):
    """Search for MP3 files matching the song name in 'AA Recordings By Song' folder and its subfolders."""
    try:
        # Escape single quotes in song_name
        escaped_song_name = song_name.replace("'", "\\'")
        query = f"name = '{escaped_song_name}.mp3' and mimeType = 'audio/mpeg' and trashed = false"
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, parents)',
            pageSize=1000
        ).execute()
        items = results.get('files', [])
        return items
    except HttpError as error:
        print(f"An error occurred: {error}")
        return []

def copy_file(file_id, new_name, destination_folder_id):
    """Copy a file to the destination folder with a new name."""
    try:
        file_metadata = {
            'name': new_name,
            'parents': [destination_folder_id]
        }
        copied_file = drive_service.files().copy(
            fileId=file_id,
            body=file_metadata
        ).execute()
        print(f"✅ Copied '{new_name}' to destination folder.")
    except HttpError as error:
        print(f"An error occurred while copying file: {error}")

# -----------------------------
# 🚀 Main Program
# -----------------------------

def main():
    # 📢 Program Summary
    print("--------------------------------------------------")
    print("🎵 newBuildRecordingsSetV01.py")
    print("This program performs the following steps:")
    print("1. Prompts for a Google Docs set folder (default: '01 Set').")
    print("2. Prompts for a destination recordings folder (default: '01 Recordings').")
    print("3. Processes files in the set folder:")
    print("   - Identifies files with '!' at the 7th character.")
    print("   - Extracts 'Set Seq ID' and song name.")
    print("   - Constructs MP3 filename.")
    print("4. Searches 'AA Recordings By Song' and its subfolders for matching MP3 files.")
    print("5. Copies matching MP3 files to the destination folder with the 'Set Seq ID' prefixed.")
    print("--------------------------------------------------\n")

    # 📝 Prompt for Set Folder
    set_folder_name = input("Enter the Google Docs set folder name (default: '01 Set'): ").strip()
    if not set_folder_name:
        set_folder_name = "01 Set"

    # 📝 Prompt for Destination Recordings Folder
    dest_folder_name = input("Enter the destination recordings folder name (default: '01 Recordings'): ").strip()
    if not dest_folder_name:
        dest_folder_name = "01 Recordings"

    # 🔍 Retrieve Folder IDs
    set_folder_id = get_folder_id(set_folder_name)
    if not set_folder_id:
        return

    dest_folder_id = get_folder_id(dest_folder_name)
    if not dest_folder_id:
        return

    # 📄 List Files in Set Folder
    files = list_files_in_folder(set_folder_id)
    if not files:
        print("No files found in the set folder.")
        return
    # Retrieve the ID of the "AA Recordings By Song" folder
    aa_recordings_folder_id = get_folder_id("AA Recordings By Song")
    if not aa_recordings_folder_id:
        print("❌ 'AA Recordings By Song' folder not found.")
        return

    # Get all subfolder IDs under "AA Recordings By Song"
    subfolder_ids = get_all_subfolder_ids(aa_recordings_folder_id)
    # Include the main folder ID as well
    subfolder_ids.append(aa_recordings_folder_id)    

    # 🎯 Process Each File
    for file in files:
        file_name = file['name']
        print(f"\nProcessing file: {file_name}")

        # Check if 7th character is '!'
        if len(file_name) >= 7 and file_name[6] == '!':
            # Extract Set Seq ID (first 6 characters)
            set_seq_id = file_name[:6]

            # Extract song name starting from 9th character up to the word 'narration'
            match = re.search(r'!\s*(.*?)\s+narration', file_name, re.IGNORECASE)
            if match:
                song_name = match.group(1)
                mp3_filename = f"{song_name}.mp3"
                print(f"Extracted Song Name: {song_name}")
                print(f"Constructed MP3 Filename: {mp3_filename}")

                # Search for matching MP3 files
                matching_files = search_mp3_files_in_folders(song_name, subfolder_ids)
                if matching_files:
                    for mp3_file in matching_files:
                        new_file_name = f"{set_seq_id} {mp3_file['name']}"
                        copy_file(mp3_file['id'], new_file_name, dest_folder_id)
                else:
                    print(f"❌ No matching MP3 files found for '{song_name}'.")
            else:
                print("❌ Could not extract song name from the file name.")
        else:
            print("Skipping file as it does not meet the naming criteria.")

if __name__ == '__main__':
    main()
