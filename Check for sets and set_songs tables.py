import sqlite3
import os

DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"

if not os.path.exists(DB_FILE):
    print(f"❌ Database file not found at {DB_FILE}")
else:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    print("Tables in DB:", cursor.fetchall())

    # Check schema if sets exists
    cursor.execute("PRAGMA table_info(sets);")
    print("\nsets schema:", cursor.fetchall())

    cursor.execute("PRAGMA table_info(set_songs);")
    print("\nset_songs schema:", cursor.fetchall())

    conn.close()


