import os
import sqlite3
from pathlib import Path

# --- Config ---
PROJECT_DIR = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
SONG_FOLDER = Path("/home/keith/Desktop/SongPDFs")
DB_FILE = PROJECT_DIR / "songs.db"

# --- Database setup ---
def init_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)  # Ensure project folder exists
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            song_id INTEGER PRIMARY KEY,
            song_name TEXT,
            file_name TEXT,
            last_revised_date TEXT,
            male_female_duet TEXT,
            time_signature TEXT,
            tempo INTEGER,
            type TEXT,
            google_docs_folder_id TEXT,
            google_docs_file_id TEXT
        )
    """)
    conn.commit()
    return conn

# --- Load song PDFs ---
def parse_filename(fname):
    """
    Example filename: Pretty Baby(KVF).2026.05.24.pdf
    Returns song_name, last_revised_date, male_female_duet
    """
    base, _ = os.path.splitext(fname)
    parts = base.split(".")

    # Detect revision date
    if len(parts) > 1 and parts[-3:].count("") == 0:
        maybe_date = ".".join(parts[-3:])
        song_name = ".".join(parts[:-3])
        last_revised_date = maybe_date
    else:
        song_name = base
        last_revised_date = None

    # Detect male/female/duet marker inside parentheses
    mf_marker = None
    if "(" in song_name and ")" in song_name:
        mf_marker = song_name.split("(")[-1].rstrip(")")
    return song_name, last_revised_date, mf_marker, fname

def load_songs():
    conn = init_db()
    cur = conn.cursor()

    for fname in sorted(os.listdir(SONG_FOLDER)):
        if not fname.lower().endswith(".pdf"):
            continue
        song_name, last_revised_date, mf_marker, full_fname = parse_filename(fname)

        cur.execute("""
            INSERT INTO songs (song_name, file_name, last_revised_date, male_female_duet)
            VALUES (?, ?, ?, ?)
        """, (song_name, full_fname, last_revised_date, mf_marker))

    conn.commit()
    conn.close()
    print(f"✅ Songs loaded into database: {DB_FILE}")

# --- Run ---
if __name__ == "__main__":
    load_songs()
