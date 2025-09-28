import sqlite3

DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"

def reset_tables():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Turn off FK checks while dropping
    cursor.execute("PRAGMA foreign_keys = OFF;")

    # Drop dependent tables first
    cursor.execute("DROP TABLE IF EXISTS set_songs;")
    cursor.execute("DROP TABLE IF EXISTS sets;")

    # Turn foreign keys back on
    cursor.execute("PRAGMA foreign_keys = ON;")

    # Recreate sets with UNIQUE set_number
    cursor.execute("""
    CREATE TABLE sets (
        set_id INTEGER PRIMARY KEY AUTOINCREMENT,
        set_number INTEGER NOT NULL UNIQUE,
        set_name TEXT,
        google_folder_id TEXT
    );
    """)

    # Recreate set_songs with FK constraints
    cursor.execute("""
    CREATE TABLE set_songs (
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
    conn.close()
    print("✅ Reset complete: 'sets' and 'set_songs' tables recreated")

if __name__ == "__main__":
    reset_tables()
