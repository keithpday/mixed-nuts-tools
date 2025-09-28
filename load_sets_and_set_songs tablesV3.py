import os
import re
import sqlite3
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

# ───────────────────────────────
# Config
# ───────────────────────────────
DB_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/songs.db")
CREDENTIALS_FILE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
TOKEN_PICKLE = os.path.expanduser("~/PythonProjects/projects/Mixed_Nuts/config/token.pickle")

# Replace this with your actual top-level folder ID
TOP_FOLDER_ID = "1_xzscUAvfWMWn1MdEF0TS6daZXCBfz8W"

SCOPES = ["https://www.googleapis.com/auth/drive"]


# ───────────────────────────────
# Google Drive Auth
# ───────────────────────────────
def get_drive_service():
    creds = None
    if os.path.exists(TOKEN_PICKLE):
        with open(TOKEN_PICKLE, "rb") as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PICKLE, "wb") as token:
            pickle.dump(creds, token)
    return build("drive", "v3", credentials=creds)


# ───────────────────────────────
# Database Init
# ───────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS songs (
        song_id INTEGER PRIMARY KEY AUTOINCREMENT,
        song_name TEXT NOT NULL,
        file_name TEXT NOT NULL,
        last_revised_date TEXT,
        male_female_duet TEXT,
        time_signature TEXT,
        tempo INTEGER,
        type TEXT,
        google_docs_folder_id TEXT,
        google_docs_file_id TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sets (
        set_id INTEGER PRIMARY KEY AUTOINCREMENT,
        set_number TEXT NOT NULL UNIQUE,   -- TEXT now (e.g., "03", "Christmas1")
        set_name TEXT,
        google_folder_id TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS set_songs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        set_id INTEGER NOT NULL,
        song_id INTEGER NOT NULL,
        sequence_number INTEGER NOT NULL,
        google_file_name TEXT NOT NULL,
        google_file_id TEXT NOT NULL,
        FOREIGN KEY (set_id) REFERENCES sets(set_id),
        FOREIGN KEY (song_id) REFERENCES songs(song_id)
    )
    """)

    conn.commit()
    return conn


# ───────────────────────────────
# Filename Parsing
# ───────────────────────────────
def parse_song_filename(fname):
    """
    Extract sequence number and base song name from "13-04 Baby Face(KVF).2020.01.01.pdf"
    Returns (seq_num, base_name) or (None, None) if not matched.
    """
    match = re.match(r"^\d+-?(\d+)\s+(.+)$", fname)
    if match:
        seq = int(match.group(1))
        base_name = match.group(2)
        return seq, base_name
    return None, None


# ───────────────────────────────
# Loader
# ───────────────────────────────
def load_sets_from_drive(top_folder_id):
    conn = init_db()
    cursor = conn.cursor()
    drive_service = get_drive_service()

    # List subfolders of top folder
    top_folders = (
        drive_service.files()
        .list(q=f"'{top_folder_id}' in parents and mimeType='application/vnd.google-apps.folder'",
              fields="files(id, name)")
        .execute()
    )

    for folder in top_folders.get("files", []):
        folder_id = folder["id"]
        folder_name = folder["name"]

        # The first token (split by space) is the set_number (string, not int)
        set_number = folder_name.split()[0]

        print(f"\n📂 Processing Set {set_number}: {folder_name}")

        # Insert/Update into sets
        cursor.execute("""
            INSERT INTO sets (set_number, set_name, google_folder_id)
            VALUES (?, ?, ?)
            ON CONFLICT(set_number) DO UPDATE SET
                set_name=excluded.set_name,
                google_folder_id=excluded.google_folder_id
        """, (set_number, folder_name, folder_id))
        conn.commit()

        # Fetch the set_id
        cursor.execute("SELECT set_id FROM sets WHERE set_number = ?", (set_number,))
        set_id = cursor.fetchone()[0]

        # List files inside the set folder
        files = (
            drive_service.files()
            .list(q=f"'{folder_id}' in parents and mimeType!='application/vnd.google-apps.folder'",
                  fields="files(id, name)")
            .execute()
        )

        for f in files.get("files", []):
            fname = f["name"]
            file_id = f["id"]

            # Skip if filename doesn’t match expected pattern
            seq, base_name = parse_song_filename(fname)
            if seq is None:
                print(f"   ⚠️ Skipping unmatched filename: {fname}")
                continue

            # Find song_id by matching base_name against songs table
            cursor.execute("SELECT song_id FROM songs WHERE file_name = ?", (base_name,))
            row = cursor.fetchone()
            song_id = row[0] if row else -1

            if song_id == -1:
                print(f"   ⚠️ Song not found in songs table: {fname}")

            # Insert into set_songs
            cursor.execute("""
                INSERT INTO set_songs (set_id, song_id, sequence_number, google_file_name, google_file_id)
                VALUES (?, ?, ?, ?, ?)
            """, (set_id, song_id, seq, fname, file_id))
            conn.commit()

            print(f"   ✅ Added seq {seq}: {fname} (song_id={song_id})")

    conn.close()
    print("\n✅ Finished loading sets and set_songs.")


# ───────────────────────────────
# Main
# ───────────────────────────────
if __name__ == "__main__":
    load_sets_from_drive(TOP_FOLDER_ID)
