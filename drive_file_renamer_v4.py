#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drive_file_rename_v4.6_mixednuts.py
───────────────────────────────────────────────────────────────
Interactive bulk renamer for Google Drive files.

Features:
  • Mixed Nuts branding
  • Help primer at startup
  • Always performs a dry-run preview before renaming
  • Undo / Restore mode with recent-log picker
  • Safe logging to logs/drive_renamer/
  • Automatic cleanup (keeps 10 most recent logs, sorted by date)
  • Optional filename filter for prefix/suffix/case modes
"""

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ──────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDS_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
TOKEN_PATH = CREDS_PATH.with_name("token_drive_renamer.json")
LOG_DIR = Path(CREDS_PATH).parent / "logs" / "drive_renamer"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────────
def get_drive_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)

# ──────────────────────────────────────────────────────────────
def show_primer():
    print("\n───────────────────────────────────────────────")
    print("🎵  Mixed Nuts Drive File Renamer  🎵")
    print("───────────────────────────────────────────────")
    print("Created by Keith Day — Legacy Performers Project\n")
    print("Available rename modes:")
    print("  • replace – find text in filenames and replace it (case-insensitive by default)")
    print("  • prefix  – add text at the beginning of filenames")
    print("  • suffix  – add text just before the file extension")
    print("  • case    – change filenames to upper, lower, or title case")
    print("\nOther options:")
    print("  • You can filter by MIME type (Docs, Sheets, PDFs, etc.)")
    print("  • You can also limit prefix/suffix/case to names containing certain text")
    print("  • The program always previews changes first (dry run)")
    print("  • After the preview, you'll be asked to proceed, cancel, or edit inputs")
    print("  • Every real rename is logged safely to:")
    print(f"      {LOG_DIR}")
    print("───────────────────────────────────────────────\n")

# ──────────────────────────────────────────────────────────────
def find_folder_id(svc, name):
    """Look up a folder ID by name (case-insensitive), allowing user to re-enter on failure."""
    while True:
        q = (
            f"mimeType = 'application/vnd.google-apps.folder' "
            f"and trashed = false "
            f"and name contains '{name}'"
        )
        res = svc.files().list(q=q, fields="files(id,name)").execute()
        folders = res.get("files", [])
        if folders:
            if len(folders) > 1:
                print("\n⚠️  Multiple folders matched:")
                for i, f in enumerate(folders, 1):
                    print(f"  {i}. {f['name']}")
                choice = input("Select a folder number (or press Enter to cancel): ").strip()
                if not choice.isdigit() or not (1 <= int(choice) <= len(folders)):
                    print("Cancelled.")
                    sys.exit(0)
                return folders[int(choice) - 1]["id"]
            return folders[0]["id"]

        print(f"\n❌ Folder not found: '{name}' (search is case-insensitive)")
        choice = input("Would you like to re-enter the folder name? (y/n): ").strip().lower()
        if choice == "y":
            name = input("Enter the correct folder name (not case-sensitive): ").strip()
            continue
        else:
            print("Operation cancelled.")
            sys.exit(0)

# ──────────────────────────────────────────────────────────────
def list_files(svc, folder_id, mime=None):
    allf, token = [], None
    while True:
        q = f"'{folder_id}' in parents and trashed = false"
        if mime:
            q += f" and mimeType contains '{mime}'"
        r = svc.files().list(
            q=q, fields="nextPageToken,files(id,name)", pageSize=100, pageToken=token
        ).execute()
        allf += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            break
    return allf

# ──────────────────────────────────────────────────────────────
def transform_name(old, mode, search, replace, prefix, suffix, case, use_regex):
    if mode == "replace":
        flags = 0 if use_regex else re.IGNORECASE
        pat = re.compile(search, flags)
        return pat.sub(replace, old)
    if mode == "prefix":
        return prefix + old
    if mode == "suffix":
        stem, ext = Path(old).stem, Path(old).suffix
        return f"{stem}{suffix}{ext}"
    if mode == "case":
        if case == "upper": return old.upper()
        if case == "lower": return old.lower()
        if case == "title": return old.title()
    return old

# ──────────────────────────────────────────────────────────────
def rename_files(svc, files, mode, search, replace, prefix, suffix, case, use_regex, filter_str, dry_run):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logpath = LOG_DIR / f"drive_renames_final_{timestamp}.csv"
    changed = []

    if dry_run:
        print("────────── Dry Run Preview (no changes made) ──────────")

    for f in files:
        old_name = f["name"]
        if filter_str and filter_str.lower() not in old_name.lower():
            continue  # skip non-matching files

        new = transform_name(old_name, mode, search, replace, prefix, suffix, case, use_regex)
        if new != old_name:
            print(f"{old_name}  →  {new}")
            changed.append((f["id"], old_name, new))
            if not dry_run:
                try:
                    svc.files().update(fileId=f["id"], body={"name": new}).execute()
                except HttpError as e:
                    print(f"⚠️  Failed: {e}")

    if changed:
        if dry_run:
            print("\n(Dry run only — no log saved)")
        else:
            with open(logpath, "w", newline="", encoding="utf-8") as c:
                w = csv.writer(c)
                w.writerow(["file_id", "old_name", "new_name"])
                w.writerows(changed)
            print(f"\n📝  Log saved to {logpath}")
    else:
        print("No changes made.")

    return len(changed)

# ──────────────────────────────────────────────────────────────
def undo_from_log(svc, log_file):
    if not Path(log_file).exists():
        print(f"❌ Log file not found: {log_file}")
        return

    with open(log_file, newline="", encoding="utf-8") as c:
        rows = list(csv.DictReader(c))
    if not rows:
        print("No entries in log.")
        return

    print(f"\nRestoring names from: {log_file}")
    for r in rows:
        print(f"{r['new_name']}  →  {r['old_name']}")

    confirm = input("\nProceed with undo (y/n): ").strip().lower()
    if confirm != "y":
        print("Undo cancelled.")
        return

    for r in rows:
        try:
            svc.files().update(fileId=r["file_id"], body={"name": r["old_name"]}).execute()
        except HttpError as e:
            print(f"⚠️  Failed to restore {r['new_name']}: {e}")

    print("\n✅ Undo complete.\n")

# ──────────────────────────────────────────────────────────────
def prune_old_logs(max_logs=10):
    """Keep only the most recent `max_logs` CSV files, delete the rest."""
    logs = sorted(LOG_DIR.glob("drive_renames_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(logs) > max_logs:
        print(f"\n🧹 Cleaning up old logs (keeping most recent {max_logs})...")
        for path in logs[max_logs:]:
            try:
                path.unlink()
                print(f"   Removed: {path.name}")
            except Exception as e:
                print(f"   ⚠️  Could not remove {path.name}: {e}")
        print("🧾 Log cleanup complete.\n")

# ──────────────────────────────────────────────────────────────
def gather_inputs():
    show_primer()
    folder = input("Enter the folder name (not case-sensitive): ").strip()
    mode = input("Select rename mode (replace / prefix / suffix / case): ").strip().lower()

    search = replace = prefix = suffix = case = filter_str = None
    use_regex = False

    if mode == "replace":
        # Preserve any leading/trailing spaces
        search = input("Enter text to find: ")
        replace = input("Enter replacement text: ")
        use_regex = input("Use regex? (y/n): ").strip().lower() == "y"

    elif mode in ["prefix", "suffix", "case"]:
        # Optional file filter
        use_filter = input("Apply only to files containing specific text? (y/n): ").strip().lower()
        if use_filter == "y":
            filter_str = input("Enter text to match in filenames: ")

        if mode == "prefix":
            prefix = input("Enter prefix to add: ")
        elif mode == "suffix":
            suffix = input("Enter suffix to add before extension: ")
        elif mode == "case":
            case = input("Choose case (upper/lower/title): ").strip().lower()

    print("\nChoose MIME filter (press Enter for all):")
    print("  doc    → Google Docs")
    print("  sheet  → Google Sheets")
    print("  slide  → Google Slides")
    print("  form   → Google Forms")
    print("  draw   → Google Drawings")
    print("  folder → Google Folders")
    print("  pdf    → PDF files")
    print("  img    → Images (JPEG, PNG)")
    print("  txt    → Plain text files")
    mime_key = input("Enter key (or full MIME type): ").strip().lower()

    mime_map = {
        "doc": "application/vnd.google-apps.document",
        "sheet": "application/vnd.google-apps.spreadsheet",
        "slide": "application/vnd.google-apps.presentation",
        "form": "application/vnd.google-apps.form",
        "draw": "application/vnd.google-apps.drawing",
        "folder": "application/vnd.google-apps.folder",
        "pdf": "application/pdf",
        "img": "image/",
        "txt": "text/plain",
    }

    mime = None
    if mime_key:
        if mime_key in mime_map:
            mime = mime_map[mime_key]
        elif "/" in mime_key:
            mime = mime_key
        else:
            print(f"⚠️  Unknown key '{mime_key}' — ignoring MIME filter.")

    if mime:
        print(f"\nFiltering for MIME type: {mime}")
    else:
        print("\nNo MIME filter applied (all files).")

    return dict(
        folder=folder, mode=mode, search=search, replace=replace,
        prefix=prefix, suffix=suffix, case=case,
        use_regex=use_regex, mime=mime, filter_str=filter_str
    )

# ──────────────────────────────────────────────────────────────
def main():
    svc = get_drive_service()
    prune_old_logs(max_logs=10)

    print("\nSelect operation: rename / undo / quit")
    op = input("> ").strip().lower()

    if op == "quit":
        print("Goodbye.")
        return

    elif op == "undo":
        logs = sorted(LOG_DIR.glob("drive_renames_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            print(f"No log files found in {LOG_DIR}")
            return

        print("\nAvailable logs:")
        for i, path in enumerate(logs[:5], 1):
            print(f"  {i}. {path.name}")
        print("  0. Cancel")

        choice = input("\nSelect a log number or enter full path: ").strip()
        if choice == "0" or not choice:
            print("Undo cancelled.")
            return
        elif choice.isdigit() and 1 <= int(choice) <= len(logs[:5]):
            log_file = logs[int(choice) - 1]
        else:
            log_file = Path(choice)

        undo_from_log(svc, log_file)
        return

    elif op == "rename":
        params = gather_inputs()
        fid = find_folder_id(svc, params["folder"])
        files = list_files(svc, fid, params["mime"])
        print(f"\nFound {len(files)} files in '{params['folder']}'.\n")

        # Always do a dry-run preview first
        print("💡 Previewing proposed changes (dry run)...\n")
        count = rename_files(
            svc, files,
            params["mode"], params["search"], params["replace"],
            params["prefix"], params["suffix"], params["case"],
            params["use_regex"], params["filter_str"], dry_run=True
        )

        if count == 0:
            print("\nNothing to rename.")
            return

        while True:
            choice = input("\nProceed with these renames for real? (y/n/edit): ").strip().lower()
            if choice == "n":
                print("Operation cancelled.")
                return
            elif choice == "edit":
                print("\nRe-enter parameters (press Enter to keep current):")
                for k, v in list(params.items()):
                    if k in ["use_regex"]:
                        cont = input(f"{k.replace('_',' ')} [{'y' if v else 'n'}]: ").strip().lower()
                        if cont in ("y", "n"):
                            params[k] = cont == "y"
                    elif k in ["prefix", "suffix", "replace", "search", "filter_str"]:
                        newv = input(f"{k.replace('_',' ')} [{v or ''}]: ")
                        if newv != "":
                            params[k] = newv
                    else:
                        newv = input(f"{k.replace('_',' ')} [{v or ''}]: ").strip()
                        if newv:
                            params[k] = newv

                # Re-run dry-run after editing
                print("\n💡 Previewing updated changes (dry run)...\n")
                count = rename_files(
                    svc, files,
                    params["mode"], params["search"], params["replace"],
                    params["prefix"], params["suffix"], params["case"],
                    params["use_regex"], params["filter_str"], dry_run=True
                )
                if count == 0:
                    print("\nNothing to rename.")
                    return
                continue
            elif choice == "y":
                print("\n🚀 Performing real rename operation...\n")
                rename_files(
                    svc, files,
                    params["mode"], params["search"], params["replace"],
                    params["prefix"], params["suffix"], params["case"],
                    params["use_regex"], params["filter_str"], dry_run=False
                )
                print("\n✅ Rename complete.")
                return
            else:
                print("Please enter 'y', 'n', or 'edit'.")
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
