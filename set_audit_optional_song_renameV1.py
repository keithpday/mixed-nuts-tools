import os
import sqlite3
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# ────────────────────────────────
# CONFIG
# ────────────────────────────────
DB_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/songs.db")
SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_JSON = os.path.expanduser(
    "~/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
)
TOKEN_PICKLE = os.path.expanduser(
    "~/PythonProjects/projects/Mixed_Nuts/config/token.pickle"
)

# ────────────────────────────────
# GOOGLE DRIVE AUTH
# ────────────────────────────────
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_JSON, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE, "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)

# ────────────────────────────────
# HELPER TO PARSE SEQUENCE NUMBER
# ────────────────────────────────
def extract_sequence(filename):
    # Expect "13-07 Song Name.pdf" → 7
    parts = filename.split(" ", 1)[0].split("-")
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return 0

# ────────────────────────────────
# AUDIT FUNCTION
# ────────────────────────────────
def audit_set(set_number):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Find set info
    cursor.execute(
        "SELECT set_id, google_folder_id FROM sets WHERE set_number = ?", (set_number,)
    )
    row = cursor.fetchone()
    if not row:
        print(f"❌ No set found for {set_number}")
        return
    set_id, parent_folder_id = row
    print(f"📂 Auditing Set {set_number} (set_id={set_id}, parent_folder_id={parent_folder_id})")

    drive_service = get_drive_service()

    # Find the "{set_number} Set" subfolder
    results = (
        drive_service.files()
        .list(
            q=f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{set_number} Set'",
            fields="files(id, name)",
        )
        .execute()
    )
    subfolders = results.get("files", [])
    if not subfolders:
        print(f"❌ Could not find subfolder '{set_number} Set'")
        return
    set_folder_id = subfolders[0]["id"]

    # List PDFs inside the set subfolder
    results = (
        drive_service.files()
        .list(
            q=f"'{set_folder_id}' in parents and mimeType='application/pdf'",
            fields="files(id, name)",
        )
        .execute()
    )
    drive_files = results.get("files", [])

    # Get set_songs from DB
    cursor.execute(
        "SELECT google_file_name, google_file_id FROM set_songs WHERE set_id = ?",
        (set_id,),
    )
    db_files = {row[0]: row[1] for row in cursor.fetchall()}

    # Track names found on Drive
    drive_names = [f["name"] for f in drive_files]

    # Step 1: Check Drive files
    for f in drive_files:
        fname = f["name"]
        fid = f["id"]

        if "!" in fname or "Set List" in fname:  # skip narrations & set lists
            continue

        if fname in db_files:
            print(f"✅ Match: {fname}")
        else:
            print(f"⚠️ Not in DB: {fname}")
            choice = input("   ➡ Add this to DB? (y/n): ").strip().lower()
            if choice == "y":
                seq = extract_sequence(fname)
                cursor.execute(
                    """
                    INSERT INTO set_songs (set_id, song_id, sequence_number, google_file_name, google_file_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (set_id, -1, seq, fname, fid),
                )
                conn.commit()
                print(f"   ✅ Added {fname} to set_songs")

    # Step 2: Check DB files missing on Drive
    for db_name in db_files.keys():
        if db_name not in drive_names:
            if "!" in db_name or "Set List" in db_name:
                continue
            print(f"⚠️ In DB but missing on Drive: {db_name}")

    conn.close()

# ────────────────────────────────
# MAIN
# ────────────────────────────────
def main():
    set_number = input("Enter set number (e.g., 13, 03, Christmas1): ").strip()
    audit_set(set_number)

if __name__ == "__main__":
    main()
