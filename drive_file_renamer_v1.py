#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DriveFileRenamer_v1.py
───────────────────────────────────────────────────────────────
Modern bulk-renaming tool for Google Drive folders.

Features:
  • Replace, add prefix/suffix, or change case
  • Dry-run preview mode
  • Optional CSV log for undo
  • Reuses OAuth token
"""

import argparse, csv, re, sys
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
# Authentication
# ──────────────────────────────────────────────────────────────
def get_drive_service():
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)

# ──────────────────────────────────────────────────────────────
# Drive helpers
# ──────────────────────────────────────────────────────────────
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
# Rename logic
# ──────────────────────────────────────────────────────────────
def transform_name(old, args):
    if args.mode == "replace":
        pat = re.compile(args.search, 0 if args.regex else re.IGNORECASE)
        return pat.sub(args.replace, old)
    if args.mode == "prefix":
        return args.prefix + old
    if args.mode == "suffix":
        stem, ext = Path(old).stem, Path(old).suffix
        return f"{stem}{args.suffix}{ext}"
    if args.mode == "case":
        if args.case == "upper": return old.upper()
        if args.case == "lower": return old.lower()
        if args.case == "title": return old.title()
    return old

def rename_files(svc, files, args):
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logpath = Path(args.logfile or f"drive_renames_{timestamp}.csv")
    changed = []

    for f in files:
        new = transform_name(f["name"], args)
        if new != f["name"]:
            print(f"{f['name']}  →  {new}")
            changed.append((f["id"], f["name"], new))
            if not args.dry_run:
                try:
                    svc.files().update(fileId=f["id"], body={"name": new}).execute()
                except HttpError as e:
                    print(f"⚠️  Failed: {e}")
    # Log
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
    p = argparse.ArgumentParser(
        description="Bulk rename Google Drive files in a folder."
    )
    p.add_argument("folder", help="Exact Drive folder name")
    p.add_argument("--mode", choices=["replace","prefix","suffix","case"],
                   default="replace")
    p.add_argument("--search", help="Text/regex to find (for replace mode)")
    p.add_argument("--replace", default="", help="Replacement text (for replace mode)")
    p.add_argument("--prefix", default="", help="Prefix to add (prefix mode)")
    p.add_argument("--suffix", default="", help="Suffix to add before extension (suffix mode)")
    p.add_argument("--case", choices=["upper","lower","title"])
    p.add_argument("--regex", action="store_true", help="Treat search as regex")
    p.add_argument("--mime", help="Filter by MIME type (e.g. application/vnd.google-apps.document)")
    p.add_argument("--dry-run", action="store_true", help="Preview only, no rename")
    p.add_argument("--logfile", help="Optional CSV log path")
    args = p.parse_args()

    svc = get_drive_service()
    fid = find_folder_id(svc, args.folder)
    files = list_files(svc, fid, args.mime)
    print(f"Found {len(files)} files.")
    rename_files(svc, files, args)

if __name__ == "__main__":
    main()
