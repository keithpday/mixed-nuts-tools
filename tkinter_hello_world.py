import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import messagebox, Listbox, Text

def greet():
    name = entry_name.get()
    choice = radio_var.get()
    chk = "Yes" if chk_var.get() else "No"
    fruit = fruit_listbox.get(ACTIVE) if fruit_listbox.curselection() else "None"
    comments = text_box.get("1.0", "end").strip()
    msg = (
        f"Hello, {name}!\n"
        f"Radio choice: {choice}\n"
        f"Checked: {chk}\n"
        f"Fruit: {fruit}\n"
        f"Comments: {comments}"
    )
    messagebox.showinfo("Greeting", msg)

def change_theme(event):
    new_theme = theme_combo.get()
    app.style.theme_use(new_theme)

# --- Window setup ---
app = tb.Window(themename="cosmo")
app.title("Modern ttkbootstrap Demo")
app.geometry("650x650")

# --- Widgets ---
frame = tb.Frame(app, padding=20)
frame.pack(fill=BOTH, expand=True)

# Theme selector
tb.Label(frame, text="Select Theme:").pack(anchor="w")
themes = app.style.theme_names()
theme_combo = tb.Combobox(frame, values=themes, state="readonly")
theme_combo.set(app.style.theme.name)   # show current theme
theme_combo.bind("<<ComboboxSelected>>", change_theme)
theme_combo.pack(pady=10, fill=X)

# Name Entry
tb.Label(frame, text="Enter your name:").pack(pady=5, anchor="w")
entry_name = tb.Entry(frame, width=30)
entry_name.pack(pady=5, fill=X)

# Checkbutton
chk_var = tb.BooleanVar()
tb.Checkbutton(
    frame, text="Subscribe to newsletter",
    variable=chk_var, bootstyle="round-toggle"
).pack(pady=10, anchor="w")

# Radiobuttons
radio_var = tb.StringVar(value="Option A")
tb.Label(frame, text="Pick an option:").pack(pady=5, anchor="w")
tb.Radiobutton(frame, text="Option A", variable=radio_var, value="Option A", bootstyle="info").pack(anchor="w")
tb.Radiobutton(frame, text="Option B", variable=radio_var, value="Option B", bootstyle="info").pack(anchor="w")

# Listbox
tb.Label(frame, text="Choose a fruit:").pack(pady=5, anchor="w")
fruit_listbox = Listbox(frame, height=4, font=("Segoe UI", 14))
for fruit in ["Apple", "Banana", "Cherry", "Date"]:
    fruit_listbox.insert("end", fruit)
fruit_listbox.pack(pady=5, fill=X)

# Text box
tb.Label(frame, text="Comments:").pack(pady=5, anchor="w")
text_box = Text(frame, height=4, font=("Segoe UI", 14))
text_box.pack(pady=5, fill=X)

# Submit Button
tb.Button(frame, text="Submit", command=greet, bootstyle="success").pack(pady=20)

# --- Run the app ---
app.mainloop()
