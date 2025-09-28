import os
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
from tkinter import Tk, filedialog, simpledialog, messagebox
from googleapiclient.discovery import build
from oauth2client import file, client, tools
import string

# Path to Poppler binaries
POPPLER_PATH = r"C:\Users\keith\OneDrive\Documents\GitHub\GoogleDriveTools\googleDriveTools\myGoogleSheetsStuff\poppler-24.08.0\Library\bin"

# Path to Tesseract executable
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Google Auth setup
SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/documents"]

store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    creds = tools.run_flow(flow, store)

drive_service = build('drive', 'v3', credentials=creds)
docs_service = build('docs', 'v1', credentials=creds)

# Helper: Find or create a Drive folder
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

# Extract song title from text
def extract_song_title(text):
    print("=== Debug: Raw OCR Text ===")
    print(text)
    print("===========================")

    # Normalize smart quotes to standard double quotes
    text = text.replace('“', '"').replace('”', '"')

    # Remove trailing whitespace and punctuation
    text = text.rstrip(string.whitespace + string.punctuation)

    # Split the text into words
    words = text.split()
    print("Words:", words)

    # Initialize variables
    title_words = []
    word_count = 0

    # Iterate over the words in reverse
    for word in reversed(words):
        print(f"Inspecting word: {word}")
        # Check if the word contains a double quote
        if '"' in word:
            # Remove the double quote and add the word to the title
            clean_word = word.replace('"', '')
            title_words.append(clean_word)
            print("Found double quote. Ending extraction.")
            break
        else:
            # Add the word to the title
            title_words.append(word)
            word_count += 1
            # Stop if we've added six words
            if word_count == 6:
                print("Reached six words. Ending extraction.")
                break

    # Reverse the list to get the correct order and join into a string
    title = ' '.join(reversed(title_words))
    print("Extracted title before stripping:", title)

    # Remove leading and trailing punctuation and quotes
    title = title.strip(string.punctuation + string.whitespace + '"')
    print("Final extracted title:", title)

    return title

# Process a single PDF file
def process_pdf(pdf_path, folder_id, set_id):
    basename = os.path.basename(pdf_path)

    images = convert_from_path(pdf_path, dpi=300, poppler_path=POPPLER_PATH)

    full_text = ""
    for image in images:
        text = pytesseract.image_to_string(image)
        full_text += text + "\n"

    # Remove page number headers (e.g., "--- Page 1 ---")
    lines = full_text.splitlines()
    lines = [line for line in lines if not line.strip().startswith('--- Page')]
    full_text = '\n'.join(lines)

    # Extract and confirm song title
    extracted_title = extract_song_title(full_text)
    confirmed_title = simpledialog.askstring("Confirm Song Title", "Please confirm or edit the song title:", initialvalue=extracted_title)
    if not confirmed_title:
        print("No song title confirmed. Skipping file.")
        return

    # Prompt for Sequence ID with the song title in the prompt
    sequence_id = simpledialog.askstring("Sequence ID", f"Enter the 2-character Sequence ID for the song:\n'{confirmed_title}'")
    if not sequence_id:
        print("No Sequence ID entered. Skipping file.")
        return

    # Construct the final document name
    doc_name = f"{set_id}-{sequence_id} ! {confirmed_title} narration"

    doc_metadata = {"name": doc_name, "mimeType": "application/vnd.google-apps.document", "parents": [folder_id]}
    doc = drive_service.files().create(body=doc_metadata, fields='id').execute()
    doc_id = doc['id']

    docs_service.documents().batchUpdate(documentId=doc_id, body={
        'requests': [{'insertText': {'location': {'index': 1}, 'text': full_text}}]
    }).execute()

    print(f"✅ Uploaded: {doc_name} → https://docs.google.com/document/d/{doc_id}/edit")

# Main program loop
def main():
    root = Tk()
    root.withdraw()

    default_base = "Narrations Source Docs"
    base_folder_name = simpledialog.askstring("Top Folder", f"Enter base folder name (default: {default_base}):")
    if not base_folder_name:
        base_folder_name = default_base
    base_folder_id = find_or_create_folder(base_folder_name)

    subfolder_name = simpledialog.askstring("Subfolder", "Enter subfolder name (e.g., 01 Narrations):")
    if not subfolder_name:
        print("No subfolder name entered. Exiting.")
        return
    subfolder_id = find_or_create_folder(subfolder_name, parent_id=base_folder_id)

    # Prompt for Set ID
    set_id = simpledialog.askstring("Set ID", "Enter the 2-character Set ID (e.g., 01):")
    if not set_id:
        print("No Set ID entered. Exiting.")
        return

    while True:
        default_dir = r"C:\Users\keith\OneDrive\Documents\GitHub\MixedNutsLib\Marked"
        file_paths = filedialog.askopenfilenames(initialdir=default_dir, title="Select PDF Files", filetypes=[("PDF files", "*.pdf")])
        if not file_paths:
            print("No files selected.")
            break

        for pdf_path in file_paths:
            process_pdf(pdf_path, subfolder_id, set_id)

        again = messagebox.askyesno("Continue?", "Would you like to process more PDF files?")
        if not again:
            break

if __name__ == "__main__":
    main()
