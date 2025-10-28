#!/usr/bin/env python3
"""
google_contacts_labeler.py
------------------------------------------------
Reviews unlabeled Google Contacts and "Other Contacts",
allowing you to assign them to:
  - SafeInbox
  - NonSafeInbox
  - Review

Press 'Q' anytime to quit gracefully.
Contacts already labeled or previously processed are skipped.
"""

import sys
import time
import json
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# === CONFIGURATION ===
TOKEN_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/token_contacts.json"
print(f"🔐 Using token file: {TOKEN_FILE}")
CREDENTIALS_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/credentials.json"
CACHE_FILE = "processed_contacts.json"

SCOPES = [
    "https://www.googleapis.com/auth/contacts",                 # Full read/write access to contacts
    "https://www.googleapis.com/auth/contacts.other.readonly",  # Read "Other Contacts"
]


LABELS = ["SafeInbox", "NonSafeInbox", "Review"]


# === LOCAL CACHE ===
def load_processed():
    """Load previously processed contacts from cache file."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def save_processed(processed):
    """Save updated processed contact IDs."""
    with open(CACHE_FILE, "w") as f:
        json.dump(list(processed), f)


# === AUTH ===
def get_service(api, version):
    print(f"🔐 Authorizing {api} API...")
    creds = None
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        print("   ✅ Loaded existing token.json credentials.")
    except Exception:
        print("   ⚠️  No valid token found, reauthorizing...")
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("   💾 Saved new token.json for future runs.")
    print(f"   ✅ {api} service ready.\n")
    return build(api, version, credentials=creds)


# === HELPERS ===
def ensure_label_exists(people, label_name):
    """Ensure that the given contact group (label) exists."""
    groups = people.contactGroups().list(pageSize=200).execute().get("contactGroups", [])
    for g in groups:
        if g["name"].lower() == label_name.lower():
            print(f"   ✅ Found existing label '{label_name}'.")
            return g["resourceName"]

    print(f"🆕 Creating contact group '{label_name}'...")
    group = people.contactGroups().create(body={"contactGroup": {"name": label_name}}).execute()
    print(f"   ✅ Created {label_name}: {group['resourceName']}")
    return group["resourceName"]


def get_contacts(people):
    """Fetch all regular contacts, including resourceName and memberships."""
    print("📇 Fetching standard contacts...")
    contacts = []
    try:
        results = people.people().connections().list(
            resourceName="people/me",
            personFields="names,emailAddresses,memberships",
            pageSize=1000,
            requestSyncToken=False
        ).execute()
        connections = results.get("connections", [])
        for c in connections:
            resource = c.get("resourceName")
            name = c.get("names", [{}])[0].get("displayName", "")
            emails = [e["value"] for e in c.get("emailAddresses", [])]
            labels = [
                m.get("contactGroupMembership", {}).get("contactGroupResourceName", "")
                for m in c.get("memberships", [])
            ]
            contacts.append({
                "resourceName": resource,
                "name": name,
                "emails": emails,
                "labels": labels
            })
        print(f"   ✅ Retrieved {len(contacts)} regular contacts.")
    except HttpError as e:
        print(f"   ⚠️  Error retrieving regular contacts: {e}")
    return contacts


def get_other_contacts(people):
    """Fetch 'Other contacts' automatically saved by Gmail."""
    print("📥 Fetching 'Other contacts'...")
    others = []
    try:
        results = people.otherContacts().list(readMask="emailAddresses", pageSize=1000).execute()
        for entry in results.get("otherContacts", []):
            for email in entry.get("emailAddresses", []):
                others.append(email["value"])
        print(f"   ✅ Found {len(others)} other contacts.")
    except HttpError as e:
        print(f"   ⚠️  Could not fetch other contacts: {e}")
    return others


def add_contact_to_label(people, contact_resource_name, label_resource_name):
    """Add a contact to a label."""
    try:
        people.contactGroups().members().modify(
            resourceName=label_resource_name,
            body={"resourceNamesToAdd": [contact_resource_name]},
        ).execute()
        print(f"   🏷️  Added contact to label successfully.")
    except HttpError as e:
        print(f"   ⚠️  Error labeling contact: {e}")


def get_choice():
    """Prompt user for label choice, with quit support."""
    choice = input("Label as [S]afeInbox, [N]onSafeInbox, [R]eview, [Enter] to skip, or [Q]uit: ").strip().lower()
    if choice == "q":
        print("\n👋 Exiting gracefully. Progress saved.\n")
        sys.exit(0)
    return choice


# === MAIN ===
def main():
    print("🚀 Starting Google Contacts Labeler...\n")

    people = get_service("people", "v1")

    # Ensure all three groups exist
    label_ids = {name: ensure_label_exists(people, name) for name in LABELS}
    label_resource_ids = set(label_ids.values())

    # Load cache
    processed = load_processed()

    # Fetch contacts
    contacts = get_contacts(people)
    other_emails = get_other_contacts(people)

    # Filter unlabeled and unprocessed contacts
    unlabeled = []
    for c in contacts:
        if c["resourceName"] in processed:
            continue

        contact_label_ids = set(c["labels"])
        has_label = any(lbl in label_resource_ids for lbl in contact_label_ids)

        if not has_label:
            unlabeled.append(c)

    print(f"\n📊 Found {len(unlabeled)} unlabeled regular contacts (excluding cached).")
    print(f"📊 Found {len(other_emails)} 'Other contacts' without any label.\n")

    if not unlabeled and not other_emails:
        print("🎉 Nothing to do. All contacts are labeled or cached.")
        return

    # Label regular contacts
    for c in unlabeled:
        name = c["name"] or "(no name)"
        email = ", ".join(c["emails"]) if c["emails"] else "(no email)"
        print(f"\nContact: {name} — {email}")
        choice = get_choice()
        if not choice:
            continue
        label = {"s": "SafeInbox", "n": "NonSafeInbox", "r": "Review"}.get(choice)
        if not label:
            continue
        add_contact_to_label(people, c["resourceName"], label_ids[label])
        processed.add(c["resourceName"])
        save_processed(processed)
        print(f"   ✅ Added to '{label}'.")

    # Label "other contacts"
    for email in other_emails:
        if email in processed:
            continue
        print(f"\nOther Contact: {email}")
        choice = get_choice()
        if not choice:
            continue
        label = {"s": "SafeInbox", "n": "NonSafeInbox", "r": "Review"}.get(choice)
        if not label:
            continue
        try:
            new_contact = people.people().createContact(body={"emailAddresses": [{"value": email}]}).execute()
            add_contact_to_label(people, new_contact["resourceName"], label_ids[label])
            processed.add(email)
            save_processed(processed)
            print(f"   ✅ Created new contact and added to '{label}'.")
        except HttpError as e:
            print(f"   ⚠️  Could not add '{email}': {e}")

    print("\n✅ All done! Contacts labeling complete.\n")


if __name__ == "__main__":
    main()
