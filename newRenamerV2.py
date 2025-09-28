import os
import sys
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.oauth2 import service_account
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

def prompt_strings():
    folder_name = input("Enter the Google Drive folder name: ").strip()
    print("Select renaming mode:")
    print("1. Replace search string with replacement value")
    print("2. Replace a number of leading characters")
    print("3. Replace a number of trailing characters (ignore file type)")
    print("4. Replace a range of characters (inclusive)")
    mode = input("Enter mode number (1-4): ").strip()

    if mode == '1':
        search = input("Enter the string to search for (case-sensitive): ")
        print(f"Search string entered: \"{search}\"")
        if not search:
            print("Error: Search string cannot be empty.")
            sys.exit(1)
        replace = input("Enter the replacement string (can be empty): ")
        print(f"Replacement string entered: \"{replace}\"")
        return folder_name, mode, {'search': search, 'replace': replace}

    elif mode == '2':
        count = int(input("Enter the number of leading characters to replace: "))
        replace = input("Enter the replacement string: ")
        return folder_name, mode, {'count': count, 'replace': replace}

    elif mode == '3':
        count = int(input("Enter the number of trailing characters to replace (ignoring file extension): "))
        replace = input("Enter the replacement string: ")
        return folder_name, mode, {'count': count, 'replace': replace}

    elif mode == '4':
        start = int(input("Enter the start position (1-based): "))
        end = int(input("Enter the end position (inclusive, 1-based): "))
        replace = input("Enter the replacement string: ")
        return folder_name, mode, {'start': start, 'end': end, 'replace': replace}

    else:
        print("Invalid mode selected.")
        sys.exit(1)

def get_folder_path(folder_id):
    path = []
    while True:
        file = drive_service.files().get(fileId=folder_id, fields="id, name, parents").execute()
        path.insert(0, file['name'])
        parents = file.get('parents')
        if not parents:
            break
        folder_id = parents[0]
    return "/".join(path)

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
            path = get_folder_path(folder['id'])
            print(f"{idx + 1}. Path: /{path} (ID: {folder['id']})")
        choice = input("Select the number of the folder you want to use: ").strip()
        if not choice.isdigit() or not (1 <= int(choice) <= len(folders)):
            print("Invalid selection.")
            sys.exit(1)
        selected_folder = folders[int(choice) - 1]
        return selected_folder['id']
    return folders[0]['id']

def list_files_in_folder(folder_id):
    query = f"'{folder_id}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

def rename_by_search_string(base, search, replace):
    if search not in base:
        return None
    return base.replace(search, replace)

def rename_by_leading_chars(base, count, replace):
    if len(base) < count:
        return None
    return replace + base[count:]

def rename_by_trailing_chars(base, count, replace):
    if len(base) < count:
        return None
    return base[:-count] + replace

def rename_by_range(base, start, end, replace):
    if len(base) < end:
        return None
    return base[:start-1] + replace + base[end:]

def main():
    folder_name, mode, params = prompt_strings()

    try:
        folder_id = get_folder_id_by_name(folder_name)
        files = list_files_in_folder(folder_id)
    except HttpError as error:
        print(f"An error occurred: {error}")
        sys.exit(1)

    if not files:
        print("No files found in the specified folder.")
        return

    changes = []
    skipped = []

    for file in files:
        filename = file['name']
        file_id = file['id']
        base, ext = os.path.splitext(filename)

        new_base = None

        if mode == '1':
            new_base = rename_by_search_string(base, params['search'], params['replace'])
        elif mode == '2':
            new_base = rename_by_leading_chars(base, params['count'], params['replace'])
        elif mode == '3':
            new_base = rename_by_trailing_chars(base, params['count'], params['replace'])
        elif mode == '4':
            new_base = rename_by_range(base, params['start'], params['end'], params['replace'])

        if new_base is None:
            skipped.append((filename, "Rename operation not possible."))
            continue

        new_name = new_base + ext

        # Check if a file with the new name already exists in the folder
        safe_new_name = new_name.replace('"', '\"')
        query = f"'{folder_id}' in parents and name=\"{safe_new_name}\" and trashed=false"
        existing_files = drive_service.files().list(q=query, fields="files(id)").execute()

        if existing_files.get('files'):
            skipped.append((filename, f"Conflict: '{new_name}' already exists."))
            continue

        changes.append((file_id, filename, new_name))

    if not changes:
        print("\nNo files matched the criteria. No changes made.")
        if skipped:
            print("\nSkipped files:")
            for fname, reason in skipped:
                print(f" - {fname}: {reason}")
        return

    print("\nProposed changes:")
    for _, old, new in changes:
        print(f"'{old}' -> '{new}'")

    if skipped:
        print("\nSkipped files:")
        for fname, reason in skipped:
            print(f" - {fname}: {reason}")

    confirm = input("\nProceed with these changes? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Operation cancelled.")
        return

    for file_id, old, new in changes:
        try:
            drive_service.files().update(fileId=file_id, body={"name": new}).execute()
            print(f"Renamed '{old}' to '{new}'")
        except HttpError as error:
            print(f"Failed to rename '{old}': {error}")

    print("\nFiles successfully renamed!")

if __name__ == "__main__":
    main()
