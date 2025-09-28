#!/usr/bin/env python3
import sqlite3
from pathlib import Path

BASE_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
DB_PATH = BASE_PATH / "script_menu.db"

# ---------------- DB helpers ----------------
def get_columns():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(menu_items)")
    cols = [row[1] for row in cur.fetchall()]  # row[1] = column name
    conn.close()
    return cols

def load_menu_items():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cols = get_columns()
    cur.execute(f"SELECT {', '.join(cols)} FROM menu_items ORDER BY option_number")
    rows = cur.fetchall()
    conn.close()
    return cols, rows

def list_items():
    cols, rows = load_menu_items()
    if not rows:
        print("\n(No items found)")
        return

    print("\nCurrent menu items:")
    print("=" * 60)

    for row in rows:
        rec = dict(zip(cols, row))
        print(f"Option:    {rec.get('option_number','')}")
        print(f"Label:     {rec.get('label','')}")
        print(f"Command:   {rec.get('command','')}")
        print(f"Type:      {rec.get('type','')}")
        print(f"Base Path: {rec.get('base_path','')}")
        print(f"Working Dir:  {rec.get('working_dir','')}")
        print(f"Program Path: {rec.get('program_path','')}")
        print("Args:")
        args_text = rec.get('args', '') or ""
        if args_text.strip():
            for line in args_text.splitlines():
                print(f"   {line}")
        else:
            print("   (none)")
        print("=" * 60)
        
# ---------------- CRUD helpers ----------------
def add_item():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    option_number = input("Option number: ").strip()
    label = input("Label: ").strip()
    command = input("Command: ").strip()
    type_ = input("Type (python/bash): ").strip()
    working_dir = input("Working dir (optional): ").strip()
    program_path = input("Program path: ").strip()
    args = input("Args (optional): ").strip()
    base_path = input("Base path (optional): ").strip()

    cur.execute("""
        INSERT INTO menu_items (option_number, label, command, type, working_dir, program_path, args, base_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (option_number, label, command, type_, working_dir, program_path, args, base_path))
    conn.commit()
    conn.close()
    print("✅ Item added.")

def update_item():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    optnum = input("Enter the option_number of the item to update: ").strip()
    field = input("Which field to update (option_number, label, command, type, working_dir, program_path, args, base_path): ").strip()
    value = input(f"New value for {field}: ").strip()

    cur.execute(f"SELECT id FROM menu_items WHERE option_number=? LIMIT 1", (optnum,))
    row = cur.fetchone()
    if not row:
        print("❌ No such option_number.")
        return
    id_ = row[0]

    cur.execute(f"UPDATE menu_items SET {field}=? WHERE id=?", (value, id_))
    conn.commit()
    conn.close()
    print("✅ Item updated.")

def delete_item():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    optnum = input("Enter the option_number of the item to delete: ").strip()
    cur.execute("SELECT id FROM menu_items WHERE option_number=? LIMIT 1", (optnum,))
    row = cur.fetchone()
    if not row:
        print("❌ No such option_number.")
        return
    id_ = row[0]

    cur.execute("DELETE FROM menu_items WHERE id=?", (id_,))
    conn.commit()
    conn.close()
    print("✅ Item deleted.")

def copy_item():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    optnum = input("Enter the option_number of the item to copy: ").strip()
    cur.execute("SELECT option_number, label, command, type, working_dir, program_path, args, base_path FROM menu_items WHERE option_number=? LIMIT 1", (optnum,))
    row = cur.fetchone()
    if not row:
        print("❌ No such option_number.")
        return

    new_opt = input(f"New option_number (was {row[0]}): ").strip() or row[0]
    new_label = input(f"New label (was {row[1]}): ").strip() or row[1]
    new_args = input(f"New args (was {row[6]}): ").strip() or row[6]

    cur.execute("""
        INSERT INTO menu_items (option_number, label, command, type, working_dir, program_path, args, base_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (new_opt, new_label, row[2], row[3], row[4], row[5], new_args, row[7]))
    conn.commit()
    conn.close()
    print("✅ Item copied.")

# ---------------- UI ----------------
def main():
    while True:
        print("\n=== 🎵 Edit Menu Items (edit_menu_items.py) ===")
        print("1. List all items")
        print("2. Add new item")
        print("3. Update existing item")
        print("4. Delete an item")
        print("5. Copy an item")
        print("0. Exit")

        choice = input("Choose an option: ").strip()

        if choice == "0":
            print("Goodbye!")
            break
        elif choice == "1":
            list_items()
        elif choice == "2":
            add_item()
        elif choice == "3":
            update_item()
        elif choice == "4":
            delete_item()
        elif choice == "5":
            copy_item()
        else:
            print("❌ Invalid choice. Please try again.")

if __name__ == "__main__":
    main()
