import gspread
from google.oauth2.service_account import Credentials
import tkinter as tk
from tkinter import scrolledtext, messagebox
from datetime import datetime

# CONFIGURATION
SHEET_ID = "1DNUvIItlQt-QXtxWMiaFuynHpDFVDDFUF379jV9hBM8"
ACCOUNT_MAPPING_TAB = "AccountMappings"
SERVICE_ACCOUNT_FILE = "/home/keith/PythonProjects/projects/Mixed_Nuts/config/my-service-account-key.json"

# Google Sheets connection
scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID)

# Load account mappings
mapping_data = sheet.worksheet(ACCOUNT_MAPPING_TAB).get_all_records()

payables_map = {}
venue_map = {}
receivables_map = {}

for row in mapping_data:
    type_ = row["Type"].strip().lower()
    short = row["ShortName"].strip()
    full = row["FullAccountName"].strip()
    if type_ == "payable":
        payables_map[short] = full
    elif type_ == "venue":
        venue_map[short] = full
    elif type_ == "receivable":
        receivables_map[short] = full

# Sequence start
seq_start = 300000

# Journal simulation logic
def simulate_journal():
    global seq_start
    output_box.delete("1.0", tk.END)
    text = input_box.get("1.0", tk.END).strip()
    if not text:
        messagebox.showerror("Error", "Please paste a gig schedule row.")
        return

    fields = text.split('\t')
    try:
        gig_date = datetime.strptime(fields[1], "%m/%d/%Y").strftime("%Y-%m-%d")
        venue = fields[2].strip()
        pay_each = float(fields[6].replace('$', '').strip())
        musicians = [name.strip() for name in fields[7:13] if name.strip() and name.lower() != "no"]
    except Exception as e:
        output_box.insert(tk.END, f"❌ Failed to parse input: {e}")
        return

    total_pay = pay_each * len(musicians)
    entries = []

    # Get mapped account names or fall back
    sales_account = venue_map.get(venue, f"Sales - {venue}")
    rcvs_account = receivables_map.get(venue, f"Rcvbls {venue}")

    entries.append((seq_start, gig_date, f"Rcvbls {venue}", sales_account, "", f"{total_pay:.2f}", ""))
    seq_start += 100
    entries.append((seq_start, gig_date, f"Rcvbls {venue}", rcvs_account, f"{total_pay:.2f}", "", ""))
    seq_start += 100
    entries.append((seq_start, gig_date, "Paid Band with cash", "Cash", "", f"{total_pay:.2f}", ""))
    seq_start += 100

    for name in musicians:
        acct_name = payables_map.get(name, f"Pay {name}")
        entries.append((seq_start, gig_date, "Pay", acct_name, f"{pay_each:.2f}", "", ""))
        seq_start += 100

    for e in entries:
        output_box.insert(tk.END, f"{e[0]}\t{e[1]}\t{e[2]}\t{e[3]}\t{e[4]}\t{e[5]}\t{e[6]}\n")

# GUI
root = tk.Tk()
root.title("Legacy Performers - Journal Entry Simulator (Mapped)")

tk.Label(root, text="Paste Band Schedule Row:").pack()
input_box = scrolledtext.ScrolledText(root, width=120, height=4, wrap=tk.WORD)
input_box.pack(padx=10, pady=5)

tk.Button(root, text="Simulate Journal Entries", command=simulate_journal).pack(pady=5)

tk.Label(root, text="Simulated Journal Entries:").pack()
output_box = scrolledtext.ScrolledText(root, width=120, height=15, wrap=tk.WORD)
output_box.pack(padx=10, pady=5)

root.mainloop()
