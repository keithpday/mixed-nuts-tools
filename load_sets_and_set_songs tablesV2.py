import os
import re
import sqlite3
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# ────────────────────────────────
# CONFIG
# ────────────────────────────────
DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"
CREDENTIALS_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
TOKEN_PICKLE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token.pickle"

# Replace with the actual folder ID for
# "AA Numbered Sets, Books, and Recordings"
TOP_FOLDER_ID = "1_xzscUAvfWMWn1MdEF0TS6daZXCBfz8W"

SCOPES = ["https://www.googleapis.com/auth/drive"]


# ────────────────────────────────
# DB Init
# ────────────────────────────────
def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    return conn


# ────────────────────────────────
# Google Drive Auth
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
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE, "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)


# ────────────────────────────────
# Helpers
# ────────────────────────────────
def parse_set_number(set_name: str) -> int:
    """Extract set number from folder name like '13 Set' -> 13"""
    m = re.match(r"(\d+)", set_name)
    return int(m.group(1)) if m else None


def parse_song_filename(fname: str):
    """
    Example: '13-04 Blue Skies(KVF).2020.01.01.pdf'
    Returns (sequence_number, song_name)
    """
    m = re.match(r"^\d+-(\d+)\s+(.+)\.pdf$", fname)
    if not m:
        return None, None
    seq = int(m.group(1))
    song_name = m.group(2)
    return seq, song_name


# ────────────────────────────────
# Main Loader
# ────────────────────────────────
def load_sets_from_drive(top_folder_id):
    drive_service = get_drive_service()
    conn = get_db_connection()
    cursor = conn.cursor()

    # Find all subfolders (set folders)
    results = (
        drive_service.files()
        .list(
            q=f"'{top_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'",
            fields="files(id, name)",
        )
        .execute()
    )
    set_folders = results.get("files", [])

    for set_folder in set_folders:
        set_folder_id = set_folder["id"]
        set_name = set_folder["name"]
        set_number = parse_set_number(set_name)
        if not set_number:
            print(f"⚠️ Skipping non-set folder: {set_name}")
            continue

        print(f"\n📂 Processing Set {set_number}: {set_name}")

        # Insert/update sets table
        cursor.execute(
            """
            INSERT INTO sets (set_number, set_name, google_folder_id)
            VALUES (?, ?, ?)
            ON CONFLICT(set_number) DO UPDATE SET
                set_name = excluded.set_name,
                google_folder_id = excluded.google_folder_id;
            """,
            (set_number, set_name, set_folder_id),
        )
        conn.commit()

        # Get DB set_id
        cursor.execute(
            "SELECT set_id FROM sets WHERE set_number = ?", (set_number,)
        )
        set_id = cursor.fetchone()[0]

        # Now list files inside this set folder
        results = (
            drive_service.files()
            .list(
                q=f"'{set_folder_id}' in parents and mimeType!='application/vnd.google-apps.folder'",
                fields="files(id, name)",
            )
            .execute()
        )
        files = results.get("files", [])

        for f in files:
            fname = f["name"]
            file_id = f["id"]

            # skip narrations (contain "!")
            if "!" in fname:
                continue

            seq, song_name = parse_song_filename(fname)
            if not seq or not song_name:
                print(f"   ⚠️ Skipping unmatched filename: {fname}")
                continue

            # Match against songs table
            cursor.execute(
                "SELECT song_id FROM songs WHERE song_name = ?", (song_name,)
            )
            row = cursor.fetchone()
            song_id = row[0] if row else -1

            if song_id == -1:
                print(f"   ⚠️ Song not found in songs table: {fname}")

            # Insert into set_songs
            cursor.execute(
                """
                INSERT INTO set_songs
                (set_id, song_id, sequence_number, google_file_name, google_file_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (set_id, song_id, seq, fname, file_id),
            )
            print(
                f"   ✅ Added seq {seq}: {fname} (song_id={song_id})"
            )

        conn.commit()

    conn.close()
    print("\n✅ Finished loading sets and set_songs.")


# ────────────────────────────────
# Run
# ────────────────────────────────
if __name__ == "__main__":
    load_sets_from_drive(TOP_FOLDER_ID)
