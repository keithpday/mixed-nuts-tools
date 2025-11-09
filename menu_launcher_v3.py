#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
menu_launcher_v3.py — Mixed Nuts Script Launcher (enhanced)
────────────────────────────────────────────────────────────
Enhancements:
  • Dynamic title shows actual program name
  • Instruction line below title
  • Right-click (Button-3) shows description popup before running
  • Fully compatible with script_menu.db/menu_items
  • ✅ Args and Keep_Open columns now both supported
  • 🪄 MENU_LAUNCHER_MODE env var prevents double "Press ENTER" pauses
"""

import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import subprocess
import os
from pathlib import Path
from datetime import datetime

# ────────────────────────────────
# Configuration
# ────────────────────────────────
BASE_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
DB_PATH = BASE_PATH / "script_menu.db"
STATUS_FILE = BASE_PATH / "menu_status.txt"


# ────────────────────────────────
# Utility functions
# ────────────────────────────────
def append_status(msg: str):
    """Append timestamped line to shared status file."""
    try:
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass


def db_connect():
    return sqlite3.connect(DB_PATH)


# ────────────────────────────────
# Main Application
# ────────────────────────────────
class ScriptMenuApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(f"🎵 Mixed Nuts Script Menu ({os.path.basename(__file__)})")

        try:
            self.state("zoomed")
        except tk.TclError:
            self.geometry("2000x2000")

        instr = ttk.Label(
            self,
            text="Click an item to run it.  Right-click an item to see its description.",
            foreground="gray40",
            font=("TkDefaultFont", 10, "italic"),
        )
        instr.pack(pady=(6, 0))

        self.conn = db_connect()
        self.menu_items = []
        self.option_numbers = []

        self._build_ui()
        self.load_menu_items()
        append_status("Menu launcher started.")

    # ────────────────────────────────
    # Build UI
    # ────────────────────────────────
    def _build_ui(self):
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=12, pady=8)

        self.listbox = tk.Listbox(frame, font=("TkDefaultFont", 11))
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.listbox.bind("<ButtonRelease-1>", self.run_selected)
        self.listbox.bind("<Return>", self.run_selected)
        self.listbox.bind("<Button-3>", self.show_description_popup)

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", pady=8)
        ttk.Button(btn_frame, text="Refresh Menu", command=self.load_menu_items).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="Cancel Last", command=self.cancel_last).pack(
            side="left", padx=4
        )
        ttk.Button(btn_frame, text="Exit", command=self.destroy).pack(
            side="right", padx=4
        )

        self.status_var = tk.StringVar(value="App started. Loaded menu items.")
        status = ttk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            background="white",
            relief="sunken",
        )
        status.pack(fill="x", padx=6, pady=(4, 6))

    # ────────────────────────────────
    # Load Menu Items
    # ────────────────────────────────
    def load_menu_items(self):
        self.listbox.delete(0, "end")
        self.menu_items.clear()
        self.option_numbers.clear()

        try:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT option_number, label, command, program_path, args, keep_open "
                "FROM menu_items ORDER BY option_number"
            )
            rows = cur.fetchall()
            for opt, label, cmd, path, args, keep_open in rows:
                display = f"{opt}. {label}"
                if cmd:
                    display += f" ({cmd})"
                elif path:
                    display += f" ({os.path.basename(path)})"
                self.listbox.insert("end", display)
                self.menu_items.append((opt, label, cmd, path, args, keep_open or "*Auto"))
                self.option_numbers.append(opt)
            self.status_var.set(f"Loaded {len(rows)} menu items.")
        except Exception as e:
            messagebox.showerror("Database Error", str(e))

    # ────────────────────────────────
    # Run Selected Item
    # ────────────────────────────────
    def run_selected(self, event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        opt_num, label, cmd, path, args, keep_open = self.menu_items[index]
        append_status(f"Running option {opt_num}: {label}")
        self.status_var.set(f"Running: {label}")

        run_path = None
        if cmd and os.path.exists(cmd.strip()):
            run_path = cmd.strip()
        elif path and os.path.exists(path.strip()):
            run_path = path.strip()
        else:
            messagebox.showerror(
                "File Not Found",
                f"No valid command or program path found for option {opt_num}.",
            )
            return

        arg_str = " ".join((args or "").splitlines())

        try:
            append_status(f"Launching in foreground for option {opt_num}: {label}")

            # Build base command
            if run_path.endswith(".py"):
                base_cmd = f'python3 "{run_path}" {arg_str}'
            else:
                base_cmd = f'bash "{run_path}" {arg_str}'

            # Determine how terminal should behave
            if keep_open == "*Yes":
                shell_cmd = (
                    f"{base_cmd}; "
                    f'if [ -n "$MENU_LAUNCHER_MODE" ]; then '
                    f'echo; echo "---- Press ENTER to close this window ----"; read; '
                    f'fi'
                )


            elif keep_open == "*No":
                shell_cmd = f"{base_cmd}"
            else:  # *Auto — keep open only if an error occurs
                shell_cmd = (
                    f"{base_cmd} || "
                    f"(echo; echo '⚠️  An error occurred. Press ENTER to close...'; read; exit)"
                )

            # 🪄 Set environment variable to prevent double ENTER pauses
            env = os.environ.copy()
            env["MENU_LAUNCHER_MODE"] = "1"

            subprocess.Popen(
                ["gnome-terminal", "--", "bash", "-c", shell_cmd],
                start_new_session=True,
                env=env,
            )

            self.status_var.set(f"Launched: {label}")

        except Exception as e:
            messagebox.showerror("Run Error", str(e))

    # ────────────────────────────────
    # Right-click popup with description
    # ────────────────────────────────
    def show_description_popup(self, event):
        try:
            index = self.listbox.nearest(event.y)
            if index < 0 or index >= len(self.option_numbers):
                return
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(index)

            opt_num = self.option_numbers[index]
            rec = self.get_menu_item(opt_num)
            if not rec:
                return

            desc = rec.get("description") or "(No description available.)"
            label = rec.get("label", f"Option {opt_num}")

            popup = tk.Toplevel(self)
            popup.title(f"{label}")
            popup.transient(self)
            popup.geometry(f"+{self.winfo_pointerx()+10}+{self.winfo_pointery()+10}")
            popup.configure(bg="white")

            frm = ttk.Frame(popup, padding=10)
            frm.pack(fill="both", expand=True)

            txt = tk.Text(frm, wrap="word", height=27, width=140)
            txt.insert("1.0", desc)
            txt.configure(state="disabled")
            txt.pack(fill="both", expand=True)

            ttk.Button(frm, text="Close", command=popup.destroy).pack(pady=6)

            popup.focus_set()
            popup.bind("<FocusOut>", lambda e: popup.destroy())

        except Exception as e:
            messagebox.showerror("Error", str(e))

    def get_menu_item(self, opt_num):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM menu_items WHERE option_number=?", (opt_num,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    # ────────────────────────────────
    # Cancel Last
    # ────────────────────────────────
    def cancel_last(self):
        append_status("Cancel last pressed.")
        self.status_var.set("Cancel last pressed.")

    # ────────────────────────────────
    # Close cleanly
    # ────────────────────────────────
    def on_close(self):
        append_status("Menu launcher closed.")
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()


# ────────────────────────────────
# Main Entry
# ────────────────────────────────
if __name__ == "__main__":
    app = ScriptMenuApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
