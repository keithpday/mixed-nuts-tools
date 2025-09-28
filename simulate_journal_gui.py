import tkinter as tk
from tkinter import messagebox, scrolledtext
from datetime import datetime

# Sample base for simulated sequence numbers
seq_start = 200000

# Simple function to parse the pasted row and simulate journal entries
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
        venue = fields[2]
        pay_each = float(fields[6].replace('$', '').strip())
        musicians = [name for name in fields[7:13] if name and name.lower() != "no"]
    except Exception as e:
        output_box.insert(tk.END, f"❌ Failed to parse input: {e}")
        return

    total_pay = pay_each * len(musicians)
    entries = []

    # Receivable and sales entries
    entries.append((seq_start, gig_date, f"Rcvbls {venue}", "Sales - Performances", "", f"{total_pay:.2f}", ""))
    seq_start += 100
    entries.append((seq_start, gig_date, f"Rcvbls {venue}", f"Rcvbls {venue}", f"{total_pay:.2f}", "", ""))
    seq_start += 100

    # Cash payout
    entries.append((seq_start, gig_date, "Paid Band with cash", "Cash", "", f"{total_pay:.2f}", ""))
    seq_start += 100

    # Individual payments
    for name in musicians:
        entries.append((seq_start, gig_date, "Pay", f"*Pay {name}", f"{pay_each:.2f}", "", ""))
        seq_start += 100

    # Show results
    for e in entries:
        output_box.insert(tk.END, f"{e[0]}\t{e[1]}\t{e[2]}\t{e[3]}\t{e[4]}\t{e[5]}\t{e[6]}\n")

# GUI setup
root = tk.Tk()
root.title("Legacy Performers - Journal Entry Simulator")

tk.Label(root, text="Paste Band Schedule Row:").pack()
input_box = scrolledtext.ScrolledText(root, width=120, height=4, wrap=tk.WORD)
input_box.pack(padx=10, pady=5)

tk.Button(root, text="Simulate Journal Entries", command=simulate_journal).pack(pady=5)

tk.Label(root, text="Simulated Journal Entries:").pack()
output_box = scrolledtext.ScrolledText(root, width=120, height=15, wrap=tk.WORD)
output_box.pack(padx=10, pady=5)

root.mainloop()
