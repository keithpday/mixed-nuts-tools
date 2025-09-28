import os
import sqlite3

# ──────────────────────────────
# Config
# ──────────────────────────────
SONGS_FOLDER = "/home/keith/Desktop/SongPDFs"
DB_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/songs.db"

# ──────────────────────────────
# Helpers
# ──────────────────────────────
def suggest_fix(fname):
    """Suggest replacing underscores with apostrophes in the filename"""
    return fname.replace("_", "'")

def update_db(old_name, new_name):
    """Update the songs table to reflect the renamed file"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE songs SET file_name = ? WHERE file_name = ?",
        (new_name, old_name)
    )
    conn.commit()
    conn.close()

# ──────────────────────────────
# Main logic
# ──────────────────────────────
def main():
    for fname in sorted(os.listdir(SONGS_FOLDER)):
        if not fname.lower().endswith(".pdf"):
            continue
        if "_" not in fname:
            continue  # only process names with underscores

        suggested = suggest_fix(fname)
        if suggested == fname:
            continue

        print(f"\nFound: {fname}")
        print(f"Suggest: {suggested}")
        choice = input("Rename? (y/n/q): ").strip().lower()

        if choice == "q":
            print("Quitting.")
            break
        elif choice == "y":
            old_path = os.path.join(SONGS_FOLDER, fname)
            new_path = os.path.join(SONGS_FOLDER, suggested)

            try:
                os.rename(old_path, new_path)
                update_db(fname, suggested)
                print(f"✅ Renamed + updated DB: {fname} → {suggested}")
            except Exception as e:
                print(f"❌ Error renaming {fname}: {e}")
        else:
            print(f"⏩ Skipped: {fname}")

    print("\nDone scanning SongPDFs.")

# ──────────────────────────────
if __name__ == "__main__":
    main()
