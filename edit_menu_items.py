#!/usr/bin/env python3
# edit_menu_items.py — Tkinter editor for script_menu.db/menu_items
# Changes:
# - Window starts 3x wider (3000x780)
# - On close, appends a status message to BASE_PATH/menu_status.txt
# - FIX: label/entry grid so fields aren't indented too far right
# - NEW: Args field is a 4-line multiline Text with scrollbar

import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import os
from datetime import datetime

# ---- Adjust if needed ----
BASE_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
DB_PATH = BASE_PATH / "script_menu.db"
STATUS_FILE = BASE_PATH / "menu_status.txt"   # menu can watch/read this
SUPPORTED_TYPES = ("python", "bash")

# ---------------- utilities ----------------
def append_status(msg: str):
    """Append a timestamped line to the shared status file."""
    try:
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        with open(STATUS_FILE, "a", encoding="utf-8") as f:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{ts}  {msg}\n")
    except Exception:
        # Do not crash app if status write fails.
        pass

# ---------------- DB helpers ----------------
def db_connect():
    return sqlite3.connect(DB_PATH)

def get_table_columns(conn, table: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in cur.fetchall()]

def load_by_option_number(conn, opt_num: int) -> dict | None:
    cols = get_table_columns(conn, "menu_items")
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(cols)} FROM menu_items WHERE option_number = ?", (opt_num,))
    row = cur.fetchone()
    if not row:
        return None
    return dict(zip(cols, row))

def load_next_prev_option(conn, current_opt: int | None, direction: int) -> int | None:
    """direction: +1 for next, -1 for prev"""
    cur = conn.cursor()
    cur.execute("SELECT option_number FROM menu_items ORDER BY option_number")
    options = [r[0] for r in cur.fetchall()]
    if not options:
        return None
    if current_opt is None:
        return options[0]
    try:
        idx = options.index(current_opt)
    except ValueError:
        options.append(current_opt)
        options.sort()
        idx = options.index(current_opt)
    idx = max(0, min(len(options) - 1, idx + direction))
    return options[idx]

def option_exists(conn, opt_num: int) -> tuple[bool, int | None]:
    cur = conn.cursor()
    cur.execute("SELECT id FROM menu_items WHERE option_number = ?", (opt_num,))
    row = cur.fetchone()
    return (row is not None, (row[0] if row else None))

def insert_item(conn, record: dict, available_cols: list[str]) -> int:
    cols = [c for c in record.keys() if c in available_cols and c != "id"]
    vals = [record[c] for c in cols]
    sql = f"INSERT INTO menu_items ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
    cur = conn.cursor()  # <-- fixed
    cur.execute(sql, vals)
    conn.commit()
    return cur.lastrowid

def update_item(conn, record: dict, available_cols: list[str]) -> None:
    if "id" not in record or record["id"] is None:
        raise ValueError("Cannot update without a valid 'id'.")
    cols = [c for c in record.keys() if c in available_cols and c not in ("id",)]
    sets = ", ".join([f"{c} = ?" for c in cols])
    vals = [record[c] for c in cols] + [record["id"]]
    sql = f"UPDATE menu_items SET {sets} WHERE id = ?"
    cur = conn.cursor()
    cur.execute(sql, vals)
    conn.commit()

def delete_item(conn, rec_id: int):
    cur = conn.cursor()
    cur.execute("DELETE FROM menu_items WHERE id = ?", (rec_id,))
    conn.commit()

# ---------------- Tk app ----------------
class MenuItemEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎛️ Edit Menu Items")
        # 3x wider than before
        self.geometry("3000x1200")

        # DB & schema
        self.conn = db_connect()
        self.cols = get_table_columns(self.conn, "menu_items")
        self.has_args = "args" in self.cols
        self.has_base_path = "base_path" in self.cols

        # Current record cache
        self.current_record: dict | None = None

        # Build UI
        self._build_ui()
        self._log("Editor ready. Enter an option number and click Load.")

        # Keyboard shortcuts
        self.bind_all("<Control-s>", lambda e: self.save())
        self.bind_all("<Control-n>", lambda e: self.new_blank())
        self.bind_all("<Control-Delete>", lambda e: self.delete())

        # Ensure we write status on any window close path
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ----- UI helpers
    def _build_ui(self):
        # Search / nav
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Option #:").pack(side="left")
        self.entry_lookup = ttk.Entry(top, width=10)
        self.entry_lookup.pack(side="left", padx=6)
        ttk.Button(top, text="Load", command=self.load_clicked).pack(side="left", padx=4)
        ttk.Button(top, text="Prev", command=lambda: self._jump(-1)).pack(side="left", padx=4)
        ttk.Button(top, text="Next", command=lambda: self._jump(+1)).pack(side="left", padx=4)
        ttk.Button(top, text="New (blank)", command=self.new_blank).pack(side="left", padx=12)

        # Form
        form = ttk.LabelFrame(self, text="Menu Item")
        form.pack(fill="both", expand=False, padx=10, pady=8, ipady=6)

        # Variables
        self.var_id = tk.StringVar()
        self.var_option = tk.StringVar()
        self.var_label = tk.StringVar()
        self.var_type = tk.StringVar(value=SUPPORTED_TYPES[0])
        self.var_command = tk.StringVar()
        self.var_working_dir = tk.StringVar()
        self.var_base_path = tk.StringVar()
        self.var_program_path = tk.StringVar()

        # --------- GRID CONFIG (indent fix) ----------
        form.columnconfigure(0, weight=0, minsize=180)  # label col fixed
        form.columnconfigure(1, weight=1)               # entry col stretches
        # ---------------------------------------------

        r = 0
        ttk.Label(form, text="ID:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_id, state="readonly").grid(row=r, column=1, sticky="we", padx=6, pady=4)
        r += 1

        ttk.Label(form, text="Option Number:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_option).grid(row=r, column=1, sticky="we", padx=6, pady=4)
        r += 1

        ttk.Label(form, text="Label:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_label).grid(row=r, column=1, sticky="we", padx=6, pady=4)
        r += 1

        ttk.Label(form, text="Type:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        self.cmb_type = ttk.Combobox(form, textvariable=self.var_type, values=SUPPORTED_TYPES, state="readonly")
        self.cmb_type.grid(row=r, column=1, sticky="w", padx=6, pady=4)
        r += 1

        ttk.Label(form, text="Command:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(form, textvariable=self.var_command).grid(row=r, column=1, sticky="we", padx=6, pady=4)
        r += 1

        # --- ARGS: multiline text with scrollbar (only if column exists) ---
        if self.has_args:
            ttk.Label(form, text="Args:").grid(row=r, column=0, sticky="ne", padx=6, pady=4)
            args_row = ttk.Frame(form)
            args_row.grid(row=r, column=1, sticky="nsew", padx=6, pady=4)
            form.rowconfigure(r, weight=0)
            self.txt_args = tk.Text(args_row, height=4, wrap="word", undo=True)
            sb_args = ttk.Scrollbar(args_row, orient="vertical", command=self.txt_args.yview)
            self.txt_args.configure(yscrollcommand=sb_args.set)
            self.txt_args.pack(side="left", fill="both", expand=True)
            sb_args.pack(side="right", fill="y")
            r += 1
        else:
            self.txt_args = None

        ttk.Label(form, text="Working Dir:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        wd_row = ttk.Frame(form)
        wd_row.grid(row=r, column=1, sticky="we", padx=6, pady=4)
        ttk.Entry(wd_row, textvariable=self.var_working_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(wd_row, text="Browse…", command=self._browse_dir_working).pack(side="left", padx=6)
        r += 1

        if self.has_base_path:
            ttk.Label(form, text="Base Path:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
            bp_row = ttk.Frame(form)
            bp_row.grid(row=r, column=1, sticky="we", padx=6, pady=4)
            ttk.Entry(bp_row, textvariable=self.var_base_path).pack(side="left", fill="x", expand=True)
            ttk.Button(bp_row, text="Browse…", command=self._browse_dir_base).pack(side="left", padx=6)
            r += 1

        ttk.Label(form, text="Program Path:").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        pp_row = ttk.Frame(form)
        pp_row.grid(row=r, column=1, sticky="we", padx=6, pady=4)
        ttk.Entry(pp_row, textvariable=self.var_program_path).pack(side="left", fill="x", expand=True)
        ttk.Button(pp_row, text="Browse…", command=self._browse_file_program).pack(side="left", padx=6)
        r += 1

        # Preview
        prev = ttk.LabelFrame(self, text="Preview")
        prev.pack(fill="x", padx=10, pady=4)
        self.lbl_preview = ttk.Label(prev, text="", anchor="w")
        self.lbl_preview.pack(fill="x", padx=8, pady=6)

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=8)
        ttk.Button(btns, text="Save (Ctrl+S)", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="Delete", command=self.delete).pack(side="left", padx=4)
        ttk.Button(btns, text="Reload", command=self.reload_current).pack(side="left", padx=12)
        ttk.Button(btns, text="Close", command=self.on_close).pack(side="right", padx=4)

        # Log (4 lines)
        logframe = ttk.LabelFrame(self, text="Log")
        logframe.pack(fill="both", expand=True, padx=10, pady=8)
        self.txt_log = tk.Text(logframe, height=4, wrap="word", state="disabled")
        sb = ttk.Scrollbar(logframe, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=sb.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Auto-update preview on field changes
        for var in (
            self.var_option, self.var_label, self.var_command,
            self.var_program_path, self.var_type
        ):
            var.trace_add("write", lambda *_: self._update_preview())

    # ----- Browsers
    def _browse_dir_working(self):
        start = self.var_working_dir.get() or str(BASE_PATH)
        d = filedialog.askdirectory(initialdir=start, title="Select Working Directory")
        if d:
            self.var_working_dir.set(d)

    def _browse_dir_base(self):
        start = self.var_base_path.get() or str(BASE_PATH)
        d = filedialog.askdirectory(initialdir=start, title="Select Base Path")
        if d:
            self.var_base_path.set(d)

    def _browse_file_program(self):
        start = self.var_program_path.get() or str(BASE_PATH)
        initialdir = start if os.path.isdir(start) else os.path.dirname(start) or str(BASE_PATH)
        f = filedialog.askopenfilename(initialdir=initialdir, title="Select Program Path")
        if f:
            self.var_program_path.set(f)

    # ----- Actions
    def load_clicked(self):
        text = self.entry_lookup.get().strip()
        if not text.isdigit():
            messagebox.showerror("Error", "Enter a valid numeric option number.")
            return
        self._load_option(int(text))

    def _jump(self, direction: int):
        cur = int(self.var_option.get()) if self.var_option.get().isdigit() else None
        opt = load_next_prev_option(self.conn, cur, direction)
        if opt is not None:
            self._load_option(opt)

    def _load_option(self, opt_num: int):
        rec = load_by_option_number(self.conn, opt_num)
        if not rec:
            self._log(f"Option {opt_num} not found.")
            answer = messagebox.askyesno("Not found", f"Option {opt_num} doesn't exist. Create new?")
            if answer:
                self.new_blank()
                self.var_option.set(str(opt_num))
            return
        self._populate_from_record(rec)
        self.entry_lookup.delete(0, "end")
        self.entry_lookup.insert(0, str(opt_num))
        self._log(f"Loaded option {opt_num} (id={rec.get('id')}).")

    def _populate_from_record(self, rec: dict):
        self.current_record = rec
        self.var_id.set("" if rec.get("id") is None else str(rec["id"]))
        self.var_option.set("" if rec.get("option_number") is None else str(rec["option_number"]))
        self.var_label.set(rec.get("label") or "")
        self.var_type.set(rec.get("type") or SUPPORTED_TYPES[0])
        self.var_command.set(rec.get("command") or "")
        if self.has_args and self.txt_args is not None:
            self.txt_args.delete("1.0", "end")
            self.txt_args.insert("1.0", rec.get("args") or "")
        self.var_working_dir.set(rec.get("working_dir") or "")
        if self.has_base_path:
            self.var_base_path.set(rec.get("base_path") or "")
        self.var_program_path.set(rec.get("program_path") or "")
        self._update_preview()

    def _collect_form(self) -> dict:
        rec = {
            "id": int(self.var_id.get()) if self.var_id.get().isdigit() else None,
            "option_number": int(self.var_option.get()) if self.var_option.get().isdigit() else None,
            "label": self.var_label.get().strip(),
            "type": self.var_type.get().strip(),
            "command": self.var_command.get().strip(),
            "working_dir": self.var_working_dir.get().strip(),
            "program_path": self.var_program_path.get().strip(),
        }
        if self.has_args and self.txt_args is not None:
            rec["args"] = self.txt_args.get("1.0", "end-1c").strip()
        if self.has_base_path:
            rec["base_path"] = self.var_base_path.get().strip()
        return rec

    def _validate(self, rec: dict) -> bool:
        if rec["option_number"] is None:
            messagebox.showerror("Validation", "Option number is required and must be numeric.")
            return False
        if not rec["label"]:
            messagebox.showerror("Validation", "Label is required.")
            return False
        if rec["type"] not in SUPPORTED_TYPES:
            messagebox.showerror("Validation", f"Type must be one of: {', '.join(SUPPORTED_TYPES)}")
            return False
        if not rec["command"] and not rec["program_path"]:
            if not messagebox.askyesno("Confirm", "No command or program_path provided. Continue?"):
                return False
        return True

    def save(self):
        rec = self._collect_form()
        if not self._validate(rec):
            return
        exists, rec_id = option_exists(self.conn, rec["option_number"])
        try:
            if rec["id"]:
                update_item(self.conn, rec, self.cols)
                self._log(f"Updated id={rec['id']} (option {rec['option_number']}).")
            else:
                if exists:
                    if not messagebox.askyesno("Overwrite?",
                                               f"Option {rec['option_number']} already exists.\n"
                                               f"Update that row instead of inserting new?"):
                        return
                    rec["id"] = rec_id
                    update_item(self.conn, rec, self.cols)
                    self._log(f"Updated existing option {rec['option_number']} (id={rec_id}).")
                else:
                    new_id = insert_item(self.conn, rec, self.cols)
                    self.var_id.set(str(new_id))
                    self._log(f"Inserted new item id={new_id} (option {rec['option_number']}).")
        except Exception as e:
            messagebox.showerror("DB Error", str(e))
            return
        self._update_preview()

    def delete(self):
        rec_id = int(self.var_id.get()) if self.var_id.get().isdigit() else None
        if not rec_id:
            messagebox.showinfo("Delete", "Nothing to delete (no ID in form).")
            return
        if not messagebox.askyesno("Confirm Delete", f"Delete item id={rec_id}? This cannot be undone."):
            return
        try:
            delete_item(self.conn, rec_id)
        except Exception as e:
            messagebox.showerror("DB Error", str(e))
            return
        self._log(f"Deleted id={rec_id}.")
        self.new_blank()

    def new_blank(self):
        self.current_record = None
        self.var_id.set("")
        self.var_option.set("")
        self.var_label.set("")
        self.var_type.set(SUPPORTED_TYPES[0])
        self.var_command.set("")
        if self.has_args and self.txt_args is not None:
            self.txt_args.delete("1.0", "end")
        self.var_working_dir.set("")
        if self.has_base_path:
            self.var_base_path.set("")
        self.var_program_path.set("")
        self._update_preview()
        self._log("New blank form.")

    def reload_current(self):
        if self.var_option.get().isdigit():
            self._load_option(int(self.var_option.get()))
        else:
            self._log("Enter a numeric option number to reload.")

    # ----- Preview & log
    def _update_preview(self):
        opt = self.var_option.get().strip() or "?"
        label = self.var_label.get().strip() or "(label)"
        cmd = self.var_command.get().strip() or self.var_program_path.get().strip()
        preview = f"{opt}. {label}"
        if cmd:
            preview += f" ({cmd})"
        self.lbl_preview.configure(text=preview)

    def _log(self, text: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", text + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    # ----- Close hook
    def on_close(self):
        try:
            opt = self.var_option.get().strip()
            label = self.var_label.get().strip()
            if opt and label:
                msg = f"Editor closed; last item on screen was option {opt} - {label}"
            else:
                msg = "Editor closed."
            append_status(msg)
        finally:
            try:
                self.conn.close()
            except Exception:
                pass
            self.destroy()

# ---------------- main ----------------
if __name__ == "__main__":
    app = MenuItemEditor()
    app.mainloop()
