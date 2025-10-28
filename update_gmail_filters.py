#!/usr/bin/env python3
"""
update_gmail_filters.py
---------------------------------------
Refresh Gmail filters based on SafeInbox / NonSafeInbox contact labels,
with automatic scope reauthorization if token lacks permissions.
"""

import os, time, json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === CONFIGURATION ===
CONTACT_LABELS = ["SafeInbox", "NonSafeInbox"]
FILTER_PREFIX = "[AUTO-FILTER]"
CHUNK_SIZE = 40
TOKEN_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token_gmail.json"
print(f"🔐 Using token file: {TOKEN_FILE}")
CREDENTIALS_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"

# Gmail + Contacts scopes
REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/contacts.readonly",
]

# === AUTHENTICATION ===
def get_service(api, version):
    print(f"🔐 Authorizing for {api}...")
    creds = None

    def reauthorize():
        """Force a new OAuth flow and save token."""
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, REQUIRED_SCOPES)
        new_creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(new_creds.to_json())
        print("   💾 Saved new token.json with full scopes.")
        return new_creds

    # Try to load existing credentials
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, REQUIRED_SCOPES)
        try:
            with open(TOKEN_FILE) as f:
                token_data = json.load(f)
            token_scopes = set(token_data.get("scopes", []))
            required_set = set(REQUIRED_SCOPES)
            if not required_set.issubset(token_scopes):
                print("   ⚠️  Token missing one or more required scopes — reauthorizing...")
                creds = reauthorize()
        except Exception as e:
            print(f"   ⚠️  Could not read token.json ({e}) — reauthorizing...")
            creds = reauthorize()
    else:
        print("   ⚠️  No token.json found — running first-time authorization...")
        creds = reauthorize()

    print(f"   ✅ {api} service ready.\n")
    return build(api, version, credentials=creds)

# === UTILITIES ===
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]

def get_label_id(gmail, label_name):
    print(f"🔎 Looking for Gmail label '{label_name}'...")
    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    for lab in labels:
        if lab["name"].lower() == label_name.lower():
            print(f"   ✅ Found Gmail label ID: {lab['id']}")
            return lab["id"]
    print(f"   🆕 Creating Gmail label '{label_name}'...")
    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    lab = gmail.users().labels().create(userId="me", body=body).execute()
    print(f"   ✅ Created label '{label_name}' (ID: {lab['id']})")
    return lab["id"]

def get_contacts_by_label(people, label_name):
    print(f"📇 Fetching contacts from label '{label_name}'...")
    try:
        groups = people.contactGroups().list(pageSize=200).execute().get("contactGroups", [])
        group_id = next((g["resourceName"] for g in groups if g["name"] == label_name), None)
        if not group_id:
            print(f"   ⚠️  Label '{label_name}' not found.")
            return []
        group = people.contactGroups().get(resourceName=group_id, maxMembers=2000).execute()
        members = group.get("memberResourceNames", [])
        print(f"   👥 Found {len(members)} contacts in '{label_name}'.")
        emails = []
        for start in range(0, len(members), 50):
            batch = members[start : start + 50]
            result = people.people().getBatchGet(resourceNames=batch, personFields="emailAddresses").execute()
            for r in result.get("responses", []):
                for e in r.get("person", {}).get("emailAddresses", []):
                    if e.get("value"):
                        emails.append(e["value"])
        unique = sorted(set(emails))
        print(f"   ✅ Extracted {len(unique)} unique email addresses.\n")
        return unique
    except HttpError as e:
        print(f"   ❌ Error retrieving contacts: {e}")
        return []

def delete_all_filters(gmail):
    print("🧹 Deleting all Gmail filters (full refresh)...")
    try:
        filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
        if not filters:
            print("   ✅ No existing filters found.")
            return
        print(f"   🗑️  Found {len(filters)} — deleting...")
        for f in filters:
            gmail.users().settings().filters().delete(userId="me", id=f["id"]).execute()
            print(f"      - Deleted {f['id']}")
            time.sleep(0.1)
        print(f"   ✅ All {len(filters)} deleted.\n")
    except HttpError as e:
        print(f"   ❌ Error deleting filters: {e}\n")

def create_filters(gmail, label_id, addresses, label_name):
    print(f"🛠️  Creating filters for '{label_name}' ({len(addresses)} emails)...")
    for i, chunk in enumerate(chunk_list(addresses, CHUNK_SIZE), start=1):
        query = f"from:({' OR '.join(chunk)})"
        if label_name == "SafeInbox":
            query += " -from:me"
        body = {
            "criteria": {"query": query},
            "action": {"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]},
        }
        try:
            gmail.users().settings().filters().create(userId="me", body=body).execute()
            print(f"   ✅ Created filter {i} ({len(chunk)} addrs).")
        except HttpError as e:
            print(f"   ❌ Filter {i} failed: {e}")
        time.sleep(0.25)
    print(f"   ✅ Completed creating filters for '{label_name}'.\n")

def main():
    print("🚀 Starting Gmail filter sync...\n")

    gmail = get_service("gmail", "v1")
    people = get_service("people", "v1")

    delete_all_filters(gmail)

    for label in CONTACT_LABELS:
        emails = get_contacts_by_label(people, label)
        if not emails:
            continue
        label_id = get_label_id(gmail, label)
        create_filters(gmail, label_id, emails, label)

    print("✅ All done! Filter sync complete.\n")

if __name__ == "__main__":
    main()
