import os
import sys
import datetime
import shutil
import re
import urllib.parse
import threading
import tkinter as tk
from tkinter import filedialog, scrolledtext
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client import file, client, tools

# Authenticate Google Drive API
SERVICE_ACCOUNT_FILE = "my-service-account-key.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]

store = file.Storage(SERVICE_ACCOUNT_FILE)
creds = store.get()
if not creds or creds.invalid:
    flow = client.flow_from_clientsecrets('credentials.json', SCOPES)
    creds = tools.run_flow(flow, store)

drive_service = build('drive', 'v3', credentials=creds)

# GUI Window Setup
root = tk.Tk()
root.title("Upload Files to Google Drive")
root.geometry("700x500")

# Output Box
output_box = scrolledtext.ScrolledText(root, width=80, height=20, wrap=tk.WORD)
output_box.pack(pady=10)

def log_message(message):
    """Append log messages to the Tkinter text box."""
    output_box.insert(tk.END, message + "\n")
    output_box.yview(tk.END)
    root.update()

def run_script():
    """Runs the script logic inside a thread to avoid freezing the GUI."""
    def script_logic():
        try:
            # Step 1: Prompt for Folder
            default_folder = r"C:\Users\keith\OneDrive\Documents\GitHub\MixedNutsLib\SetPublishStage"
            folder_path = filedialog.askdirectory(initialdir=default_folder, title="Select Folder")
            if not folder_path:
                log_message("No folder selected. Exiting.")
                return

            # Step 2: Prompt for Set Name
            set_name = simple_prompt("Enter the Set Name (Google folder name):")
            if not set_name:
                log_message("No Set Name provided. Exiting.")
                return

            # Step 3: Prompt for Revision Date
            default_revision_date = datetime.date.today().strftime("%Y.%m.%d")
            revision_date = simple_prompt(f"Enter the Revision Date (default: {default_revision_date}):") or default_revision_date

            log_message(f"📂 Selected Folder: {folder_path}")
            log_message(f"📂 Google Set Folder: {set_name}")
            log_message(f"📅 Revision Date: {revision_date}")

            # Processing Files
            for file_name in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file_name)
                if os.path.isfile(file_path):
                    log_message(f"📄 Processing file: {file_name}")
                    
                    # Simulate processing
                    shutil.copy(file_path, os.path.join(folder_path, f"processed_{file_name}"))
                    log_message(f"✅ Successfully processed: {file_name}")

            log_message("✅ All files processed successfully!")

        except Exception as e:
            log_message(f"⚠ Error: {str(e)}")

    threading.Thread(target=script_logic, daemon=True).start()

def simple_prompt(prompt_text):
    """Creates a small popup window for user input."""
    popup = tk.Toplevel(root)
    popup.title("Input Required")
    tk.Label(popup, text=prompt_text).pack(pady=10)
    
    entry = tk.Entry(popup)
    entry.pack(pady=5)
    
    def submit():
        global user_input
        user_input = entry.get()
        popup.destroy()
    
    tk.Button(popup, text="OK", command=submit).pack(pady=5)
    popup.wait_window()  # Wait for the popup to close
    return user_input

# Run Button
run_button = tk.Button(root, text="Run Script", command=run_script, font=("Arial", 12), bg="blue", fg="white")
run_button.pack(pady=10)

# Start Tkinter GUI
root.mainloop()
