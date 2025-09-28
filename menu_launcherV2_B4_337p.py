import tkinter as tk
from tkinter import StringVar
import sqlite3
import subprocess
from pathlib import Path

# Paths
project_dir = Path.home() / "PythonProjects" / "projects" / "Mixed_Nuts"
db_path = project_dir / "script_menu.db"

# Load menu items from SQLite database
def load_menu_items():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT label, command, type, working_dir, program_path, args FROM menu_items ORDER BY option_number")
    items = cursor.fetchall()
    conn.close()
    return items

# Launch script in terminal
def launch_script(command, script_type, working_dir, program_path, args, label):
    status.set(f"Running: {label}")
    terminal_cmd = []

    wd = working_dir if working_dir else str(project_dir)

    if script_type == 'python':
        full_path = program_path if program_path else str(Path(wd) / command)
        terminal_cmd = ["gnome-terminal", "--", "python3", full_path] + args.split()
    elif script_type == 'bash':
        full_path = str(Path(wd) / command)
        terminal_cmd = ["gnome-terminal", "--", "/bin/bash", full_path] + args.split()
    else:
        status.set(f"Unknown type: {script_type}")
        return

    subprocess.Popen(terminal_cmd, cwd=wd)
    root.after(500, lambda: status.set("Idle"))

# Tkinter GUI
root = tk.Tk()
root.title("Mixed Nuts Script Menu V2")
root.geometry("1200x1200")  # Increased window size

tk.Label(root, text="Select a script to run:", font=("Arial", 14)).pack(pady=10)

menu_frame = tk.Frame(root)
menu_frame.pack(padx=20, anchor="w")

menu_items = load_menu_items()
for item in menu_items:
    label, command, script_type, working_dir, program_path, args = item
    label_text = f"{label} ({command})"
    button = tk.Button(menu_frame, text=label_text, anchor="w", width=80,
                       command=lambda c=command, t=script_type, w=working_dir, p=program_path, a=args, l=label_text:
                           launch_script(c, t, w, p, a, l))
    button.pack(fill="x", pady=2)

status = StringVar(value="Idle")
tk.Label(root, textvariable=status, font=("Arial", 10), fg="blue").pack(pady=10, anchor="w", padx=20)

root.mainloop()
