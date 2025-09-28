# TOP_FOLDER_ID = "1_xzscUAvfWMWn1MdEF0TS6daZXCBfz8W"
import os
import re
import sqlite3
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from oauth2client import file, client, tools

# ──────────────────────────────
# Config
# ──────────────────────────────
DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"

SERVICE_ACCOUNT_FILE = os.path.expanduser(
    "~/PythonProjects/projects/Mixed_Nuts/config/my-service-account-key.json"
)
SCOPES = ["https://www.googleapis.com/auth/drive"]

# Replace this with the actual ID of "AA Numbered Sets, Books, and Recordings"
TOP_FOLDER_ID = "1_xzscUAvfWMWn1MdEF0TS6daZXCBfz8W"

# ──────────────────────────────
# DB Helpers
# ──────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sets (
        set_id INTEGER PRIMARY KEY AUTOINCREMENT,
        set_number INTEGER NOT NULL,
        set_name TEXT
    );
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
    );
    """)

    conn.commit()
    return conn

# ──────────────────────────────
# Google Drive Auth
# ──────────────────────────────
def get_drive_service():
    store = file.Storage(SERVICE_ACCOUNT_FILE)
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(
            os.path.expanduser(
                "~/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
            ),
            SCOPES,
        )
        creds = tools.run_flow(flow, store)

    return build("drive", "v3", credentials=creds)

# ──────────────────────────────
# Filename Helpers
# ──────────────────────────────
def normalize_filename(google_file_name: str) -> str:
    """
    Strips leading set/sequence prefix (e.g. "13-02 ") from Google Drive filenames
    so they match entries in the songs table.
    """
    return re.sub(r'^\d{1,2}-\d{2}\s+', '', google_file_name)

# ──────────────────────────────
# Load Sets + Set Songs
# ──────────────────────────────
def load_sets_from_drive(top_folder_id):
    conn = init_db()
    cursor = conn.cursor()
    drive_service = get_drive_service()

    try:
        # Get all numbered set folders under the top folder
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
            set_number_str = set_folder["name"]  # e.g. "13"
            if not set_number_str.isdigit():
                continue

            set_number = int(set_number_str)

            # Find the "XX Set" folder inside
            subresults = (
                drive_service.files()
                .list(
                    q=f"'{set_folder['id']}' in parents and mimeType='application/vnd.google-apps.folder'",
                    fields="files(id, name)",
                )
                .execute()
            )
            subfolders = subresults.get("files", [])
            set_subfolder = next((f for f in subfolders if f["name"].endswith("Set")), None)
            if not set_subfolder:
                continue

            set_name = set_subfolder["name"]

            # Insert set into DB if not already
            cursor.execute("SELECT set_id FROM sets WHERE set_number=?", (set_number,))
            row = cursor.fetchone()
            if row:
                set_id = row[0]
            else:
                cursor.execute(
                    "INSERT INTO sets (set_number, set_name) VALUES (?, ?)",
                    (set_number, set_name),
                )
                set_id = cursor.lastrowid

            print(f"\n📂 Processing Set {set_number}: {set_name}")

            # List PDFs in the "XX Set" folder
            pdfs = (
                drive_service.files()
                .list(
                    q=f"'{set_subfolder['id']}' in parents and mimeType='application/pdf'",
                    fields="files(id, name, id)",
                )
                .execute()
                .get("files", [])
            )

            for pdf in pdfs:
                fname = pdf["name"]
                if "!" in fname:  # Skip narrations
                    continue

                # Parse filename: e.g. "13-02 Baby Face(KVF)..."
                match = re.match(r"(\d+)-(\d+)\s+(.+)\.pdf", fname)
                if not match:
                    print(f"  ⚠️ Unrecognized filename: {fname}")
                    continue

                seq_num = int(match.group(2))
                google_file_name = fname
                google_file_id = pdf["id"]

                # Normalize filename to match songs table
                normalized_name = normalize_filename(fname)

                # Lookup song_id from songs table
                cursor.execute(
                    "SELECT song_id FROM songs WHERE file_name = ?", (normalized_name,)
                )
                song_row = cursor.fetchone()
                if song_row:
                    song_id = song_row[0]
                else:
                    print(f"  ⚠️ Song not found in songs table: {normalized_name}")
                    song_id = -1  # fallback

                # Insert into set_songs
                cursor.execute(
                    """INSERT INTO set_songs
                       (set_id, song_id, sequence_number, google_file_name, google_file_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (set_id, song_id, seq_num, google_file_name, google_file_id),
                )

                print(f"  ✅ Added seq {seq_num}: {normalized_name} (song_id={song_id})")

            conn.commit()

    except HttpError as error:
        print(f"❌ An error occurred: {error}")
    finally:
        conn.close()


if __name__ == "__main__":
    load_sets_from_drive(TOP_FOLDER_ID)
    print("\n✅ Finished loading sets and set_songs.")
