import datetime
import pandas as pd
import re
import webbrowser
from googleapiclient.discovery import build
from oauth2client import file, client, tools

# --- Authenticate ---
SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents"
]

store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    creds = tools.run_flow(flow, store)

# Services
drive_service = build('drive', 'v3', credentials=creds)
sheets_service = build('sheets', 'v4', credentials=creds)
docs_service = build('docs', 'v1', credentials=creds)

# --- Setup ---
spreadsheet_id = "1WS4-Y2M7qA0bqMhluvWOg3GiUyScBSY3ZIBPoNS7Tao"
sheet_name = "CurrentYrSched"
range_name = f"{sheet_name}!A:Z"

# --- Read Sheet ---
sheet = sheets_service.spreadsheets()
result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
values = result.get('values', [])

if not values:
    print("⚠ No data found in the sheet.")
    exit()

headers = values[0]
rows = values[1:]
df = pd.DataFrame(rows, columns=headers)

# --- Prompt for Start Date ---
while True:
    start_date_input = input("Enter the start date (Sunday) of the week (MM/DD/YYYY): ").strip()
    try:
        start_date = datetime.datetime.strptime(start_date_input, "%m/%d/%Y").date()
        if start_date.weekday() != 6:
            print("⚠ The date you entered is not a Sunday. Please try again.")
            continue
        break
    except ValueError:
        print("⚠ Invalid date format. Please enter as MM/DD/YYYY.")

end_date = start_date + datetime.timedelta(days=6)

# --- Filter Rows ---
df['Date'] = pd.to_datetime(df['Date'], format="%m/%d/%Y", errors='coerce')
mask = (df['Date'] >= pd.Timestamp(start_date)) & (df['Date'] <= pd.Timestamp(end_date))
week_rows = df[mask]

# --- Subject Line ---
start_month = start_date.strftime("%B")
start_day = start_date.day
end_month = end_date.strftime("%B")
end_day = end_date.day
end_year = end_date.year

if start_date.month == end_date.month:
    subject = f"Mixed Nuts week of {start_month} {start_day} - {end_day}, {end_year}"
else:
    subject = f"Mixed Nuts week of {start_month} {start_day} - {end_month} {end_day}, {end_year}"

# --- Folder Setup ---
def find_or_create_folder(name, parent_id=None):
    query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    response = drive_service.files().list(q=query, fields="files(id, name)").execute()
    folders = response.get("files", [])
    if folders:
        return folders[0]['id']
    metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        metadata["parents"] = [parent_id]
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder['id']

root_id = find_or_create_folder("Mixed Nuts Files")
weekly_id = find_or_create_folder("Weekly Emails", parent_id=root_id)

# --- Create Google Doc ---
doc_metadata = {
    'name': subject,
    'mimeType': 'application/vnd.google-apps.document',
    'parents': [weekly_id]
}
doc = drive_service.files().create(body=doc_metadata, fields='id').execute()
doc_id = doc['id']

# --- Compose the body ---
body_text = f"Hello Team.\n\nHere is the schedule for the Mixed Nuts week of {start_month} {start_day} - {end_month} {end_day}, {end_year}:\n\n"

if not week_rows.empty:
    col_widths = {col: max(len(str(col)), *(len(str(val)) for val in week_rows[col])) for col in week_rows.columns}
    header_row = " | ".join(f"{col:<{col_widths[col]}}" for col in week_rows.columns)
    separator = "-+-".join("-" * col_widths[col] for col in week_rows.columns)
    body_text += header_row + "\n" + separator + "\n"

    for _, row in week_rows.iterrows():
        row_line = " | ".join(f"{str(row[col]):<{col_widths[col]}}" for col in week_rows.columns)
        body_text += row_line + "\n"
else:
    body_text += "(No scheduled items for this week.)\n"

body_text += "\nBest,\n-Keith"

# --- Insert text ---
docs_service.documents().batchUpdate(documentId=doc_id, body={
    'requests': [{
        'insertText': {
            'location': {'index': 1},
            'text': body_text
        }
    }]
}).execute()

# --- Output ---
doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
print(f"\n✅ Created Google Doc: {doc_url}")
webbrowser.open(doc_url)
