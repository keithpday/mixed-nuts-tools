#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drive_file_rename_v2.py
───────────────────────────────────────────────────────────────
Interactive version of Drive File Renamer.
Prompts user for all inputs instead of requiring command-line args.
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

SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDS_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json")
TOKEN_PATH = CREDS_PATH.with_name("token_drive_renamer.json")

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

def find_folder_id(svc, name):
    q = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res = svc.files().list(q=q, fields="files(id,name)").execute()
    if not res["files"]:
        print(f"❌ Folder not found: {name}")
        sys.exit(1)
    return res["files"][0]["id"]

def list_files(svc, folder_id, mime=None):
    allf, token = [], None
    while True:
        q = f"'{folder_id}' in parents and trashed = false"
        if mime:
            q += f" and mimeType='{mime}'"
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
def rename_files(svc, files, mode, search, replace, prefix, suffix, case, use_regex, dry_run):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logpath = Path(f"drive_renames_{timestamp}.csv")
    changed = []

    for f in files:
        new = transform_name(f["name"], mode, search, replace, prefix, suffix, case, use_regex)
        if new != f["name"]:
            print(f"{f['name']}  →  {new}")
            changed.append((f["id"], f["name"], new))
            if not dry_run:
                try:
                    svc.files().update(fileId=f["id"], body={"name": new}).execute()
                except HttpError as e:
                    print(f"⚠️  Failed: {e}")
    # Log results
    if changed:
        with open(logpath, "w", newline="", encoding="utf-8") as c:
            w = csv.writer(c)
            w.writerow(["file_id", "old_name", "new_name"])
            w.writerows(changed)
        print(f"\n📝  Log saved to {logpath}")
    else:
        print("No changes made.")

# ──────────────────────────────────────────────────────────────
def main():
    print("\nGoogle Drive Bulk File Renamer")
    print("───────────────────────────────")

    folder = input("Enter the folder name: ").strip()
    mode = input("Select rename mode (replace / prefix / suffix / case): ").strip().lower()

    search = replace = prefix = suffix = case = None
    use_regex = False

    if mode == "replace":
        search = input("Enter text to find: ").strip()
        replace = input("Enter replacement text: ").strip()
        use_regex = input("Use regex? (y/n): ").strip().lower() == "y"
    elif mode == "prefix":
        prefix = input("Enter prefix to add: ").strip()
    elif mode == "suffix":
        suffix = input("Enter suffix to add before extension: ").strip()
    elif mode == "case":
        case = input("Choose case (upper/lower/title): ").strip().lower()

    mime = input("Optional MIME filter (press Enter for all): ").strip() or None
    dry_run = input("Dry run only? (y/n): ").strip().lower() == "y"

    svc = get_drive_service()
    fid = find_folder_id(svc, folder)
    files = list_files(svc, fid, mime)
    print(f"\nFound {len(files)} files in '{folder}'.\n")

    rename_files(svc, files, mode, search, replace, prefix, suffix, case, use_regex, dry_run)

# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
