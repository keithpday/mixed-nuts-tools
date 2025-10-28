#!/usr/bin/env python3
"""
update_gmail_filters.py (debug version)
---------------------------------------
Adds detailed debug output for visibility at each step.
"""

import time
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === CONFIGURATION ===
CONTACT_LABELS = ["SafeInbox", "NonSafeInbox"]
FILTER_PREFIX = "[AUTO-FILTER]"
CHUNK_SIZE = 40
TOKEN_FILE = "token.json"
CREDENTIALS_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/contacts.readonly",
]

# === AUTHENTICATION ===
def get_service(api, version):
    print(f"🔐 Authorizing for {api}...")
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        print("   ✅ Loaded existing token.json credentials.")
    except Exception:
        print("   ⚠️  No valid token found, using credentials.json to reauthorize.")
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("   💾 Saved new token.json for future runs.")
    print(f"   ✅ {api} service ready.\n")
    return build(api, version, credentials=creds)

# === HELPERS ===
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def get_label_id(gmail, label_name):
    print(f"🔎 Looking for Gmail label '{label_name}'...")
    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    for lab in labels:
        if lab["name"].lower() == label_name.lower():
            print(f"   ✅ Found Gmail label ID: {lab['id']}")
            return lab["id"]
    # Create if missing
    print(f"   🆕 Label '{label_name}' not found. Creating it...")
    body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    lab = gmail.users().labels().create(userId="me", body=body).execute()
    print(f"   ✅ Created new Gmail label '{label_name}' with ID: {lab['id']}")
    return lab["id"]

# === CONTACT RETRIEVAL ===
def get_contacts_by_label(people, label_name):
    print(f"📇 Fetching contacts from label '{label_name}'...")
    try:
        groups = people.contactGroups().list(pageSize=200).execute().get("contactGroups", [])
        group_id = next(
            (
                g["resourceName"]
                for g in groups
                if g["name"].lower().startswith(label_name.lower())
            ),
            None
        )

        if not group_id:
            print(f"   ⚠️  Contact label '{label_name}' not found in Google Contacts.")
            return []
        print(f"   ✅ Found contact group resource: {group_id}")
        group = people.contactGroups().get(resourceName=group_id, maxMembers=2000).execute()
        #############
        members = group.get("memberResourceNames", [])
        print(f"   👥 Found {len(members)} contacts in '{label_name}' group.")
        emails = []

        for start in range(0, len(members), 50):
            batch = members[start:start+50]
            try:
                result = people.people().getBatchGet(
                    resourceNames=batch,
                    personFields="emailAddresses"
                ).execute()

                responses = result.get("responses", [])
                for r in responses:
                    person = r.get("person", {})
                    for e in person.get("emailAddresses", []):
                        val = e.get("value", "").strip().lower()
                        if val:
                            emails.append(val)

                    # Normalize and deduplicate
                    unique_emails = sorted(set(emails))

                print(f"     ...retrieved {min(start+50, len(members))} contacts so far")
                time.sleep(1)  # tiny pause between batches just to stay gentle
            except Exception as e:
                print(f"     ❌ Batch {start//50+1} failed: {e}")
                time.sleep(3)

        unique_emails = sorted(set(emails))
        print(f"   ✅ Extracted {len(unique_emails)} unique email addresses.\n")
        return unique_emails 
        ################
    except HttpError as e:
        print(f"   ❌ Error retrieving contacts for '{label_name}': {e}")
        return []

# === FILTER MANAGEMENT ===
def delete_old_filters(gmail):
    print("🧹 Deleting all existing Gmail filters (full refresh)...")
    try:
        filters = gmail.users().settings().filters().list(userId="me").execute().get("filter", [])
        if not filters:
            print("   ✅ No existing filters found.")
            return
        print(f"   🗑️  Found {len(filters)} existing filters — deleting...")
        for f in filters:
            fid = f["id"]
            gmail.users().settings().filters().delete(userId="me", id=fid).execute()
            print(f"      - Deleted filter ID: {fid}")
            time.sleep(0.2)
        print(f"   ✅ All {len(filters)} filters deleted.\n")
    except HttpError as e:
        print(f"   ❌ Error deleting filters: {e}\n")


def create_filters(gmail, label_id, addresses, label_name):
    print(f"🛠️  Creating new Gmail filters for '{label_name}' ({len(addresses)} addresses)...")
    if not addresses:
        print("   ⚠️  No addresses to create filters for.")
        return
    for i, chunk in enumerate(chunk_list(addresses, CHUNK_SIZE), start=1):
        from_str = " OR ".join(chunk)

        # Define Gmail filter actions based on label type
        if label_name in ["SafeInbox", "NonSafeInbox"]:
            # Both SafeInbox and NonSafeInbox skip the Inbox
            action = {
                "addLabelIds": [label_id],
                "removeLabelIds": ["INBOX"],   # Skip the Inbox
                "shouldArchive": True
            }
        else:
            # (future-proof fallback)
            action = {
                "addLabelIds": [label_id]
            }


        # Add exclusion for self-sent messages
        if label_name == "SafeInbox":
            query = f"from:({from_str}) -from:me"
        else:
            query = f"from:({from_str})"

        body = {
            "criteria": {"query": query},
            "action": action,
        }


        try:
            gmail.users().settings().filters().create(userId="me", body=body).execute()
            print(f"   ✅ Created filter {i} with {len(chunk)} addresses for {label_name}.")
        except HttpError as e:
            print(f"   ❌ Failed to create filter {i}: {e}")
        time.sleep(0.3)

    print(f"   ✅ Completed creating filters for '{label_name}'.\n")

def create_forwarding_filter(gmail):
    print("📨 Ensuring SafeInbox mail is forwarded to kdaybass@gmail.com...")
    try:
        body = {
            "criteria": {"query": "label:SafeInbox"},
            "action": {"forward": "kdaybass@gmail.com"}
        }
        gmail.users().settings().filters().create(userId="me", body=body).execute()
        print("   ✅ Forwarding filter created successfully.")
    except HttpError as e:
        print(f"   ⚠️  Could not create forwarding filter: {e}")

# === MAIN ===
def main():
    print("🚀 Starting Gmail filter sync...\n")

    gmail = get_service("gmail", "v1")
    people = get_service("people", "v1")

    delete_old_filters(gmail)

    for label_name in CONTACT_LABELS:
        emails = get_contacts_by_label(people, label_name)
        print(f"📬 {label_name}: {len(emails)} email(s) ready for filter creation.")
        if not emails:
            continue
        label_id = get_label_id(gmail, label_name)
        create_filters(gmail, label_id, emails, label_name)
        
    create_forwarding_filter(gmail)

    print("✅ All done! Filter sync complete.\n")

if __name__ == "__main__":
    main()
