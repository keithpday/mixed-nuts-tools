#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drive_file_renamer_v7.py
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
  • Smart folder lookup (exact → startswith → limited partial)
  • Interactive regex help, examples, and validation
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
    print("  • (r)eplace – find text in filenames and replace it (case-insensitive by default)")
    print("  • (p)refix  – add text at the beginning of filenames")
    print("  • (s)uffix  – add text just before the file extension")
    print("  • (c)ase    – change filenames to upper, lower, or title case")
    print("\nOther options:")
    print("  • You can filter by MIME type (Docs, Sheets, PDFs, etc.)")
    print("  • You can also limit prefix/suffix/case to names containing certain text")
    print("  • The program always previews changes first (dry run)")
    print("  • After the preview, you'll be asked to proceed, cancel, or edit inputs")
    print("  • Every real rename is logged safely to:")
    print(f"      {LOG_DIR}")
    print("───────────────────────────────────────────────\n")

# ──────────────────────────────────────────────────────────────
def explain_regex(pattern: str):
    """Quick heuristic explanation of common regex tokens."""
    explanations = {
        "^": "start of filename/text",
        "$": "end of filename/text",
        "\\d": "a digit (0–9)",
        "\\s": "a whitespace (space, tab, newline)",
        "\\w": "a word character (A–Z, a–z, 0–9, or _)",
        ".": "any single character (except newline)",
        ".*": "any sequence of characters",
        "+": "one or more of the previous element",
        "*": "zero or more of the previous element",
        "?": "zero or one of the previous element",
        "[ ]": "a literal space (inside brackets)",
        "()": "grouping for captured text",
        "|": "OR (alternative match)",
    }
    found = [f"   {k:<6} → {desc}" for k, desc in explanations.items() if k in pattern]
    return "\n".join(found) if found else "   (No special regex tokens detected)"

# ──────────────────────────────────────────────────────────────
def find_folder_id(svc, name):
    """Smart folder lookup: exact → startswith → contains (limited)."""
    name = name.strip()
    name_lower = name.lower()
    q = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = svc.files().list(q=q, fields="files(id,name)").execute()
    folders = res.get("files", [])

    # Exact
    exact = [f for f in folders if f["name"].lower() == name_lower]
    if exact:
        fid = exact[0]["id"]
        print(f"\n✅ Found exact match: {exact[0]['name']}")
        print(f"📁 Using folder: {exact[0]['name']} (ID: {fid})")
        return fid

    # Startswith
    start_matches = [f for f in folders if f["name"].lower().startswith(name_lower)]
    if start_matches:
        print("\n✅ Found close match (starts with):")
        for i, f in enumerate(start_matches, 1):
            print(f"  {i}. {f['name']}")
        choice = input("Select a folder number or press Enter to cancel: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(start_matches):
            sel = start_matches[int(choice) - 1]
            print(f"\n📁 Using folder: {sel['name']} (ID: {sel['id']})")
            return sel["id"]
        else:
            print("Operation cancelled.")
            sys.exit(0)

    # Contains fallback
    q = f"name contains '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = svc.files().list(q=q, fields="files(id,name)").execute()
    matches = res.get("files", [])[:5]
    if matches:
        print("\n⚠️ No exact match found; showing closest partial matches:")
        for i, f in enumerate(matches, 1):
            print(f"  {i}. {f['name']}")
        choice = input("Select a folder number or press Enter to cancel: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            sel = matches[int(choice) - 1]
            print(f"\n📁 Using folder: {sel['name']} (ID: {sel['id']})")
            return sel["id"]
        else:
            print("Operation cancelled.")
            sys.exit(0)

    print(f"\n❌ No folders found matching '{name}'")
    sys.exit(0)

# ──────────────────────────────────────────────────────────────
def list_files(svc, folder_id, mime=None):
    files, token = [], None
    while True:
        q = f"'{folder_id}' in parents and trashed = false"
        if mime:
            q += f" and mimeType contains '{mime}'"
        r = svc.files().list(q=q, fields="nextPageToken,files(id,name)", pageSize=100, pageToken=token).execute()
        files += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            break
    return files

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
        old = f["name"]
        if filter_str and filter_str.lower() not in old.lower():
            continue
        new = transform_name(old, mode, search, replace, prefix, suffix, case, use_regex)
        if new != old:
            print(f"{old}  →  {new}")
            changed.append((f["id"], old, new))
            if not dry_run:
                try:
                    svc.files().update(fileId=f["id"], body={"name": new}).execute()
                except HttpError as e:
                    print(f"⚠️ Failed: {e}")

    if changed:
        if dry_run:
            print("\n(Dry run only — no log saved)")
        else:
            with open(logpath, "w", newline="", encoding="utf-8") as c:
                w = csv.writer(c)
                w.writerow(["file_id", "old_name", "new_name"])
                w.writerows(changed)
            print(f"\n📝 Log saved to {logpath}")
    else:
        print("No changes made.")
    return len(changed)

# ──────────────────────────────────────────────────────────────
def undo_from_log(svc, log_file):
    path = Path(log_file)
    if not path.exists():
        print(f"❌ Log not found: {path}")
        return
    with open(path, newline="", encoding="utf-8") as c:
        rows = list(csv.DictReader(c))
    if not rows:
        print("No entries in log.")
        return
    print(f"\nRestoring names from: {path}")
    for r in rows:
        print(f"{r['new_name']} → {r['old_name']}")
    if input("\nProceed with undo (y/n): ").strip().lower() != "y":
        print("Undo cancelled.")
        return
    for r in rows:
        try:
            svc.files().update(fileId=r["file_id"], body={"name": r["old_name"]}).execute()
        except HttpError as e:
            print(f"⚠️ Failed to restore {r['new_name']}: {e}")
    print("\n✅ Undo complete.\n")

# ──────────────────────────────────────────────────────────────
def prune_old_logs(max_logs=10):
    logs = sorted(LOG_DIR.glob("drive_renames_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(logs) > max_logs:
        print(f"\n🧹 Cleaning old logs (keeping {max_logs})...")
        for p in logs[max_logs:]:
            try:
                p.unlink()
                print(f"   Removed {p.name}")
            except Exception as e:
                print(f"   ⚠️ {p.name}: {e}")
        print("🧾 Log cleanup complete.\n")

# ──────────────────────────────────────────────────────────────
def gather_inputs():
    show_primer()
    folder = input("Enter the folder name (not case-sensitive): ").strip()
    mode = input("Select rename mode ((r)eplace / (p)refix / (s)uffix / (c)ase): ").strip().lower()
    mode = {"r": "replace", "p": "prefix", "s": "suffix", "c": "case"}.get(mode, mode)

    search = replace = prefix = suffix = case = filter_str = None
    use_regex = False

    if mode == "replace":
        search = input("Enter text to find (case-insensitive): ")
        replace = input("Enter replacement text (can be blank): ")
        use_regex = input("For a more complex rename use regex? (y/n): ").strip().lower() == "y"
        if use_regex:
            print("\n💡 Regex Tips — popular examples:")
            print("   • ^.{5}           → removes first 5 characters")
            print("   • .{3}$           → removes last 3 characters")
            print("   • ^Copy of        → removes 'Copy of' at start")
            print("   • copy$           → removes 'copy' at end")
            print("   • (\\d{3})         → matches any 3-digit number")
            print("   • [ ]+$           → trims trailing spaces")
            print("   • ^[ ]+           → trims leading spaces")
            print("   • (.*)( copy)$    → removes ' copy' at end")
            print("   • (.*?) -         → removes everything after first dash")
            print("   • [^A-Za-z0-9]+   → removes special characters")
            print("   • (\\s+)           → replaces multiple spaces (replacement=' ')")
            print("   • (\\d{2})-(\\d{2})-(\\d{4}) → reorders date (replacement='\\3-\\1-\\2')\n")
            print("🪄 Tip: Leave replacement blank to delete matches.")
            print("📚 Beginner: https://regexone.com/")
            print("📘 Advanced: https://www.regular-expressions.info/\n")

            while True:
                search = input("Enter your regex pattern: ")
                try:
                    re.compile(search)
                except re.error as e:
                    print(f"⚠️ Invalid regex: {e}")
                    if input("Edit and retry? (y/n): ").strip().lower() == "y":
                        continue
                    search = None
                    break
                print("\n🧩 Quick interpretation:")
                print(explain_regex(search))
                next_step = input("\nProceed, edit, or cancel? (p/e/c): ").strip().lower()
                if next_step == "p":
                    break
                elif next_step == "e":
                    continue
                else:
                    print("Regex setup cancelled.")
                    search = None
                    break

    elif mode in ["prefix", "suffix", "case"]:
        if input("Apply only to files containing specific text? (y/n): ").strip().lower() == "y":
            filter_str = input("Enter text to match in filenames: ")
        if mode == "prefix":
            prefix = input("Enter prefix to add: ")
        elif mode == "suffix":
            suffix = input("Enter suffix to add before extension: ")
        elif mode == "case":
            case = input("Choose case ((u)pper/(l)ower/(t)itle): ").strip().lower()
            case = {"u": "upper", "l": "lower", "t": "title"}.get(case, case)

    mime_key = input("\nChoose MIME filter (press Enter for all): ").strip().lower()
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
    mime = mime_map.get(mime_key, mime_key if "/" in mime_key else None)
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

    op = input("\nSelect operation: (r)ename / (u)ndo / (q)uit: ").strip().lower()
    op = {"r": "rename", "u": "undo", "q": "quit"}.get(op, op)

    if op == "quit":
        print("Goodbye.")
        return

    elif op == "undo":
        logs = sorted(LOG_DIR.glob("drive_renames_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            print(f"No log files found in {LOG_DIR}")
            return

        print("\nAvailable logs:")
        for i, p in enumerate(logs[:5], 1):
            print(f"  {i}. {p.name}")
        c = input("\nSelect log number or path (0=cancel): ").strip()
        if c == "0" or not c:
            print("Undo cancelled.")
            return
        log_file = logs[int(c)-1] if c.isdigit() and 1 <= int(c) <= len(logs[:5]) else Path(c)
        undo_from_log(svc, log_file)
        return

    elif op == "rename":
        params = gather_inputs()
        fid = find_folder_id(svc, params["folder"])
        files = list_files(svc, fid, params["mime"])
        print(f"\nFound {len(files)} files in '{params['folder']}'.\n")

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
                print("\nRe-enter parameters (Enter=keep current):")
                for k, v in list(params.items()):
                    if k in ["use_regex"]:
                        cont = input(f"{k} [{'y' if v else 'n'}]: ").strip().lower()
                        if cont in ("y", "n"):
                            params[k] = cont == "y"
                    elif k in ["prefix", "suffix", "replace", "search", "filter_str"]:
                        newv = input(f"{k} [{v or ''}]: ")
                        if newv != "":
                            params[k] = newv
                    else:
                        newv = input(f"{k} [{v or ''}]: ").strip()
                        if newv:
                            params[k] = newv

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
