#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import subprocess
import sys
import shlex
import signal
from pathlib import Path

BASE_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
DB_PATH = BASE_PATH / "script_menu.db"
STATUS_FILE = BASE_PATH / "menu_status.txt"
SUPPORTED_TYPES = {"python", "bash"}

# ---------------- tiny tailer (status file watcher) ----------------
class StatusWatcher:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.fp = None
        self.inode = None
        self.pos = 0

    def open(self):
        try:
            self.fp = self.path.open("r", encoding="utf-8", errors="replace")
            st = self.path.stat()
            self.inode = st.st_ino
            self.fp.seek(st.st_size)  # start at end
            self.pos = self.fp.tell()
        except FileNotFoundError:
            self.fp = None
            self.inode = None
            self.pos = 0

    def poll_new_lines(self):
        try:
            st = self.path.stat()
        except FileNotFoundError:
            if self.fp is not None:
                self.close()
            return []
        # rotation/truncation/new file
        if self.fp is None or self.inode != st.st_ino or st.st_size < self.pos:
            self.close()
            self.open()
            return []
        self.fp.seek(self.pos)
        data = self.fp.read()
        self.pos = self.fp.tell()
        return data.splitlines() if data else []

    def close(self):
        try:
            if self.fp:
                self.fp.close()
        finally:
            self.fp = None
            self.inode = None
            self.pos = 0

# ---------------- DB Helpers ----------------
def load_menu_items():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(menu_items)")
    cols = {row[1] for row in cur.fetchall()}
    base_cols = ["id", "option_number", "label", "command", "type", "working_dir", "program_path"]
    opt_cols  = [c for c in ("args", "base_path") if c in cols]
    select_cols = base_cols + opt_cols
    cur.execute(f"SELECT {', '.join(select_cols)} FROM menu_items ORDER BY option_number")
    rows = cur.fetchall()
    conn.close()

    items = []
    for row in rows:
        rec = dict(zip(select_cols, row))
        rec.setdefault("args", "")
        rec.setdefault("base_path", "")
        items.append(rec)
    return items

# ---------------- Command Builders ----------------
def _resolve_base_dir(item: dict) -> Path:
    wd = (item.get("working_dir") or "").strip()
    bp = (item.get("base_path") or "").strip()
    if wd:
        return Path(wd)
    if bp:
        return Path(bp)
    return BASE_PATH

def _resolve_program_path(item: dict, base_dir: Path) -> Path | None:
    prog = (item.get("program_path") or "").strip()
    if prog:
        p = Path(prog)
        return p if p.is_absolute() else (base_dir / p)
    cmd = (item.get("command") or "").strip()
    if not cmd:
        return None
    tokens = shlex.split(cmd)
    if not tokens:
        return None
    first = tokens[0]
    p = Path(first)
    return p if p.is_absolute() else (base_dir / p)

def _gather_args(item: dict) -> list[str]:
    out = []
    args_text = (item.get("args") or "").strip()
    if args_text:
        out.extend(shlex.split(args_text))
    cmd = (item.get("command") or "").strip()
    if cmd:
        toks = shlex.split(cmd)
        if len(toks) > 1:
            out.extend(toks[1:])
    return out

def build_command(item: dict):
    type_ = (item.get("type") or "").strip().lower()
    if type_ not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported type: {type_}")
    base_dir = _resolve_base_dir(item)
    script_path = _resolve_program_path(item, base_dir)
    if not script_path:
        raise ValueError("No program_path or command specified.")
    args = _gather_args(item)

    if type_ == "python":
        argv = [sys.executable, str(script_path)] + args
    elif type_ == "bash":
        argv = ["bash", str(script_path)] + args
    else:
        argv = [str(script_path)] + args
    return argv, base_dir, type_

# ---------------- Tkinter App ----------------
class MenuLauncherApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎵 Mixed Nuts Script Menu")
        self.geometry("1200x1800")

        # --- Style: force true left-justified ttk buttons (theme-agnostic) ---
        self.style = ttk.Style(self)
        self.style.layout(
            "LeftJust.TButton",
            [("Button.border", {"sticky": "nswe", "children": [
                ("Button.focus", {"sticky": "nswe", "children": [
                    ("Button.padding", {"sticky": "nswe", "children": [
                        ("Button.label", {"sticky": "w"})
                    ]})
                ]})
            ]})]
        )
        self.style.configure("LeftJust.TButton", anchor="w")

        # Track running processes (for "Cancel Last")
        self.running_procs = []  # list of {"proc": Popen, "label": str}

        # Frame for list
        self.frame = ttk.Frame(self)
        self.frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Scrollable area for menu items
        canvas = tk.Canvas(self.frame)
        self.scrollbar = ttk.Scrollbar(self.frame, orient="vertical", command=canvas.yview)
        self.scroll_frame = ttk.Frame(canvas)
        self.scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=self.scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Log area (shows 4 lines at a time)
        log_frame = ttk.Frame(self)
        log_frame.pack(fill="x", padx=10, pady=5)
        self.log = tk.Text(log_frame, height=4, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        # Bottom control buttons
        control_frame = ttk.Frame(self)
        control_frame.pack(fill="x", pady=5)
        ttk.Button(control_frame, text="Refresh Menu", command=self.refresh_items).pack(side="left", padx=10)
        ttk.Button(control_frame, text="Cancel Last", command=self.cancel_last).pack(side="left", padx=10)
        ttk.Button(control_frame, text="Exit", command=self.on_close).pack(side="right", padx=10)

        # Load menu items
        self.item_buttons = []
        self.load_items()
        self.log_message("App started. Loaded menu items.")

        # Status-file watcher
        self._status_watcher = StatusWatcher(STATUS_FILE)
        self._status_watcher.open()
        self.after(1000, self._poll_status_file)

        # Close hook
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- status file tailing
    def _poll_status_file(self):
        for line in self._status_watcher.poll_new_lines():
            self.log_message(line)
        self.after(1000, self._poll_status_file)

    # ---- logging
    def log_message(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---- items
    def clear_items(self):
        for btn in self.item_buttons:
            btn.destroy()
        self.item_buttons = []

    def load_items(self):
        self.clear_items()
        items = load_menu_items()
        for item in items:
            cmd_display = item.get("command") or item.get("program_path") or ""
            text = f"{item['option_number']}. {item['label']} ({cmd_display})"
            btn = ttk.Button(
                self.scroll_frame,
                text=text,
                style="LeftJust.TButton",
                command=lambda i=item: self.run_item(i)
            )
            btn.pack(fill="x", pady=2)
            self.item_buttons.append(btn)
        self.log_message(f"Loaded {len(items)} menu items.")

    def refresh_items(self):
        self.log_message("Refreshing menu...")
        self.load_items()
        self._prune_finished()

    # ---- running & cancel
    def _prune_finished(self):
        self.running_procs = [info for info in self.running_procs if info["proc"].poll() is None]

    def cancel_last(self):
        self._prune_finished()
        if not self.running_procs:
            self.log_message("No running process to cancel.")
            return
        info = self.running_procs.pop()
        p = info["proc"]
        label = info.get("label", "(unknown)")
        self.log_message(f"Attempting to cancel: {label}")
        try:
            p.send_signal(signal.SIGINT)  # ask nicely
        except Exception as e:
            self.log_message(f"Cancel error: {e}")
            return
        try:
            p.wait(timeout=2)
            self.log_message(f"Canceled: {label}")
        except Exception:
            try:
                p.terminate()
                self.log_message(f"Terminated: {label}")
            except Exception as e:
                self.log_message(f"Force terminate error: {e}")

    def run_item(self, item):
        label = item.get("label") or "(unnamed)"
        try:
            argv, cwd, _type = build_command(item)
            self.log_message(f"Running: {label}")
            # Same-terminal run: inherit stdin/stdout/stderr; no new session
            proc = subprocess.Popen(argv, cwd=str(cwd))
            self.running_procs.append({"proc": proc, "label": label})
        except Exception as e:
            messagebox.showerror("Error", f"Could not run {label}\n\n{e}")
            self.log_message(f"❌ Failed: {label}")

    # ---- close
    def on_close(self):
        # Best effort: terminate any children still running
        for info in list(self.running_procs):
            p = info["proc"]
            try:
                if p.poll() is None:
                    p.terminate()
            except Exception:
                pass
        self.destroy()

# ---------------- Main ----------------
if __name__ == "__main__":
    app = MenuLauncherApp()
    app.mainloop()
