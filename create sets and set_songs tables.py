import sqlite3

DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"

conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# Create sets table
cursor.execute("""
CREATE TABLE IF NOT EXISTS sets (
    set_id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_number INTEGER NOT NULL,
    set_name TEXT
);
""")

# Create set_songs table
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
conn.close()

print("✅ sets and set_songs tables created (if they didn't already exist).")



