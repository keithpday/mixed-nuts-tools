#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Console Manager (CCM) — v7
• Shows ALL cron jobs: CCM-managed + External (outside CCM block)
• New "Sync" column with emoji+text status (✅ In Sync, 🟡 Pending, ⚠️ Differs, 🔴 Orphan)
• Color cues per-row based on Sync status
• Preferences dialog: UI scale + window size (stored in prefs.json)
• Search (case-insensitive partial) across expr/command/description/category/tags
• Double-click row → popup full description
• DB beside this script; backups in ./backups/
• Preserves unmanaged crontab content; writes only CCM block
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "Cron Console Manager (CCM)"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = SCRIPT_DIR
DB_PATH = os.path.join(BASE_DIR, "cron_jobs.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
PREFS_PATH = os.path.join(BASE_DIR, "prefs.json")

# CCM block markers
CCM_BEGIN = "# ==== CCM BEGIN ===="
CCM_END   = "# ==== CCM END ===="
CCM_MARKER_RE = re.compile(r"^#\s*\[CCM:id=(\d+)\]\s*$")

# ---------- Preferences ----------
DEFAULT_PREFS = {
    "scaling": 2.0,       # Tk scaling for HiDPI/4K
    "width": 3300,
    "height": 1560
}

def load_prefs():
    try:
        if os.path.exists(PREFS_PATH):
            with open(PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_PREFS, **data}
    except Exception:
        pass
    return DEFAULT_PREFS.copy()

def save_prefs(d):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        messagebox.showerror(APP_NAME, f"Failed to save preferences:\n{e}")

# ---------- Utilities ----------
def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run(cmd, input_text=None):
    """Run a command, return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, input=input_text, text=True,
                           capture_output=True, check=False)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {' '.join(cmd)}"

def cron_available():
    rc2, *_ = run(["which", "crontab"])
    return rc2 == 0

def read_crontab_text():
    rc, out, err = run(["crontab", "-l"])
    if rc == 0:
        return out
    # No crontab for user → treat as empty
    return ""

def write_crontab_text(text):
    return run(["crontab", "-"], input_text=text)

def backup_crontab():
    text = read_crontab_text()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, f"crontab-{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    return path

def split_crontab_sections(text):
    """Return (prefix_lines, ccm_block_lines, suffix_lines)."""
    lines = text.splitlines()
    if CCM_BEGIN in lines and CCM_END in lines:
        b = lines.index(CCM_BEGIN)
        e = lines.index(CCM_END)
        prefix = lines[:b]
        ccm = lines[b+1:e]
        suffix = lines[e+1:]
        return prefix, ccm, suffix
    else:
        return lines, [], []

def join_crontab(prefix, ccm_block, suffix):
    out = []
    out.extend(prefix)
    if out and out[-1].strip() != "":
        out.append("")
    out.append(CCM_BEGIN)
    out.extend(ccm_block)
    out.append(CCM_END)
    if suffix:
        out.append("")
        out.extend(suffix)
    return ("\n".join(out)).rstrip() + "\n"

def is_cron_expr_valid(expr):
    """Basic 5-field cron validator; allows @reboot/@daily/etc."""
    expr = expr.strip()
    if expr.startswith("@"):
        return expr in {
            "@reboot", "@yearly", "@annually", "@monthly",
            "@weekly", "@daily", "@hourly"
        }
    parts = expr.split()
    if len(parts) != 5:
        return False
    token_re = re.compile(r'^(\*|\d+|\*/\d+|\d+-\d+|\d+(,\d+)+|\d+-\d+/\d+|\*/\d+(,\*/\d+)*)$')
    for p in parts:
        if not token_re.match(p):
            return False
    return True

# Parse a CCM block into list of tuples: (id, enabled, expr, command)
def parse_ccm_block(ccm_lines):
    result = []
    i = 0
    while i < len(ccm_lines):
        m = CCM_MARKER_RE.match(ccm_lines[i].strip())
        if m and i+1 < len(ccm_lines):
            jid = int(m.group(1))
            line = ccm_lines[i+1]
            enabled = True
            raw = line.strip()
            if raw.startswith("#"):
                enabled = False
                raw = raw[1:].lstrip()
            parts = raw.split(None, 5)
            if raw.startswith("@"):
                sp = raw.split(None, 1)
                if len(sp) == 2:
                    expr = sp[0]
                    command = sp[1]
                    result.append((jid, enabled, expr, command))
            elif len(parts) >= 6:
                expr = " ".join(parts[:5])
                command = parts[5]
                result.append((jid, enabled, expr, command))
            i += 2
            continue
        i += 1
    return result

# Generic cron-line parser (for external lines too)
CRON_5_RE = re.compile(r"""
    ^\s*
    (?P<pre>\#\s*)?
    (?:
        (?P<at>@(?:reboot|yearly|annually|monthly|weekly|daily|hourly))
        \s+(?P<cmd_at>.+)
      |
        (?P<m>\S+)\s+(?P<h>\S+)\s+(?P<dom>\S+)\s+(?P<mon>\S+)\s+(?P<dow>\S+)\s+(?P<cmd>.+)
    )
    \s*$
""", re.VERBOSE)

def parse_cron_line_optional(line):
    if not line.strip():
        return None
    m = CRON_5_RE.match(line)
    if not m:
        return None
    commented = bool(m.group('pre'))
    if m.group('at'):
        expr = m.group('at')
        command = m.group('cmd_at')
        return (not commented, expr, command)
    expr = " ".join([m.group('m'), m.group('h'), m.group('dom'), m.group('mon'), m.group('dow')])
    command = m.group('cmd')
    return (not commented, expr, command)

# ---------- SQLite ----------
def ensure_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
          id INTEGER PRIMARY KEY,
          cron_expr   TEXT NOT NULL,
          command     TEXT NOT NULL,
          enabled     INTEGER NOT NULL DEFAULT 1,
          description TEXT,
          category    TEXT,
          tags        TEXT,
          created_at  TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn

def db_upsert_job(conn, job):
    if job.get("id"):
        conn.execute("""
            UPDATE jobs SET cron_expr=?, command=?, enabled=?, description=?, category=?, tags=?,
                           updated_at=datetime('now')
            WHERE id=?
        """, (job["cron_expr"], job["command"], int(job["enabled"]),
              job.get("description"), job.get("category"), job.get("tags"),
              job["id"]))
        conn.commit()
        return job["id"]
    else:
        cur = conn.execute("""
            INSERT INTO jobs (cron_expr, command, enabled, description, category, tags)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job["cron_expr"], job["command"], int(job["enabled"]),
              job.get("description"), job.get("category"), job.get("tags")))
        conn.commit()
        return cur.lastrowid

def db_delete_job(conn, job_id):
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()

def db_get_all(conn):
    cur = conn.execute("""
        SELECT id, cron_expr, command, enabled, description, category, tags
        FROM jobs ORDER BY id ASC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def db_get_by_id(conn, job_id):
    cur = conn.execute("""
        SELECT id, cron_expr, command, enabled, description, category, tags
        FROM jobs WHERE id=?
    """, (job_id,))
    r = cur.fetchone()
    if not r:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, r))

# ---------- Preferences Dialog ----------
class PrefsDialog(tk.Toplevel):
    def __init__(self, master, prefs):
        super().__init__(master)
        self.title("Preferences")
        self.resizable(False, False)
        self.result = None
        pad = {'padx': 10, 'pady': 8}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        self.var_scaling = tk.DoubleVar(value=prefs.get("scaling", DEFAULT_PREFS["scaling"]))
        self.var_w = tk.IntVar(value=prefs.get("width", DEFAULT_PREFS["width"]))
        self.var_h = tk.IntVar(value=prefs.get("height", DEFAULT_PREFS["height"]))

        ttk.Label(frm, text="UI Scaling (e.g., 1.0, 1.5, 2.0):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_scaling, width=12).grid(row=0, column=1, sticky="w")

        ttk.Label(frm, text="Window Width:").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_w, width=12).grid(row=1, column=1, sticky="w")

        ttk.Label(frm, text="Window Height:").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_h, width=12).grid(row=2, column=1, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(10,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        self.grab_set()
        self.focus()

    def on_save(self):
        try:
            s = float(self.var_scaling.get())
            w = int(self.var_w.get())
            h = int(self.var_h.get())
            if s <= 0 or w < 640 or h < 480:
                raise ValueError
        except Exception:
            messagebox.showwarning(APP_NAME, "Please enter valid numeric values.")
            return
        self.result = {"scaling": s, "width": w, "height": h}
        self.destroy()

# ---------- Dialogs ----------
class JobDialog(tk.Toplevel):
    def __init__(self, master, title, init=None):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.result = None

        init = init or {}
        pad = {'padx': 8, 'pady': 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, **pad)

        self.var_expr = tk.StringVar(value=init.get("cron_expr", "0 */4 * * *"))
        self.var_cmd  = tk.StringVar(value=init.get("command", ""))
        self.var_en   = tk.BooleanVar(value=bool(init.get("enabled", True)))
        self.var_cat  = tk.StringVar(value=init.get("category", ""))
        self.var_tags = tk.StringVar(value=init.get("tags", ""))

        ttk.Label(frm, text="Cron expression (5-field or @daily/@reboot):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_expr, width=50).grid(row=1, column=0, sticky="we")

        ttk.Label(frm, text="Command:").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cmd, width=80).grid(row=3, column=0, sticky="we")

        ttk.Checkbutton(frm, text="Enabled", variable=self.var_en).grid(row=4, column=0, sticky="w")

        ttk.Label(frm, text="Description:").grid(row=5, column=0, sticky="w")
        self.txt_desc = tk.Text(frm, width=80, height=8, wrap="word")
        self.txt_desc.grid(row=6, column=0, sticky="we")
        self.txt_desc.insert("1.0", init.get("description", "") or "")

        ttk.Label(frm, text="Category:").grid(row=7, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cat, width=30).grid(row=8, column=0, sticky="we")

        ttk.Label(frm, text="Tags (comma-sep):").grid(row=9, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_tags, width=50).grid(row=10, column=0, sticky="we")

        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, sticky="e", pady=(8,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        # Avoid Enter closing the dialog; only Ctrl+Enter saves
        self.bind("<Control-Return>", lambda e: self.on_save())
        self.grab_set()
        self.focus()

    def on_save(self):
        expr = self.var_expr.get().strip()
        cmd  = self.var_cmd.get().strip()
        if not expr or not cmd:
            messagebox.showwarning(APP_NAME, "Cron expression and command are required.")
            return
        if not is_cron_expr_valid(expr):
            messagebox.showwarning(APP_NAME, "Cron expression looks invalid.\nExample: 0 */4 * * *")
            return
        self.result = {
            "cron_expr": expr,
            "command": cmd,
            "enabled": self.var_en.get(),
            "description": self.txt_desc.get("1.0", "end").rstrip() or None,
            "category": self.var_cat.get().strip() or None,
            "tags": self.var_tags.get().strip() or None,
        }
        self.destroy()

# ---------- App ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.prefs = load_prefs()
        # Apply scaling + window size
        self.tk.call('tk', 'scaling', self.prefs.get("scaling", DEFAULT_PREFS["scaling"]))
        self.title(APP_NAME)
        self.geometry(f"{self.prefs.get('width', DEFAULT_PREFS['width'])}x{self.prefs.get('height', DEFAULT_PREFS['height'])}")

        self.conn = ensure_db()
        self.external_rows = []  # list of dicts for external jobs
        self.ccm_cron_map = {}   # id -> (enabled, expr, command) from crontab
        self.sync_map = {}       # id -> ("✅ In Sync" | "🟡 Pending" | "⚠️ Differs")

        # Styles (row colors by sync)
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=46)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 14, "bold"))

        # Toolbar
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        # Left group: DB actions
        ttk.Button(top, text="Run Now", command=self.run_now).pack(side="left", padx=4)
        ttk.Button(top, text="Enable/Disable", command=self.toggle_enable).pack(side="left", padx=4)
        ttk.Button(top, text="Delete", command=self.delete_job).pack(side="left", padx=4)
        ttk.Button(top, text="Edit", command=self.edit_job).pack(side="left", padx=4)
        ttk.Button(top, text="Add", command=self.add_job).pack(side="left", padx=4)

        # Right group: Cron + Prefs
        ttk.Button(top, text="Backup crontab only", command=self.do_backup).pack(side="right", padx=6)
        ttk.Button(top, text="Apply CCM section to cron", command=self.apply_to_cron).pack(side="right", padx=6)
        ttk.Button(top, text="Edit crontab (xed)", command=self.edit_crontab_with_xed).pack(side="right", padx=6)
        ttk.Button(top, text="Reload from crontab", command=self.reload_from_cron).pack(side="right", padx=6)
        ttk.Button(top, text="Preferences", command=self.open_prefs).pack(side="right", padx=6)

        # Search
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.var_search = tk.StringVar()
        entry = ttk.Entry(search_frame, textvariable=self.var_search, width=50)
        entry.pack(side="left", padx=(4, 8), fill="x", expand=True)
        ttk.Button(search_frame, text="Clear", command=lambda: self.var_search.set("")).pack(side="left")
        self.var_search.trace_add("write", lambda *args: self.refresh_table())

        # Columns
        cols = ("id","enabled","sync","source","cron_expr","command","description","category","tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=40)
        for c, label in [
            ("id", "Id"),
            ("enabled", "En"),
            ("sync", "Sync"),
            ("source", "Src"),
            ("cron_expr", "Cron Expr"),
            ("command", "Command"),
            ("description", "Description"),
            ("category", "Category"),
            ("tags", "Tags")
        ]:
            self.tree.heading(c, text=label)

        # Column widths
        self.tree.column("id", width=90, anchor="center")
        self.tree.column("enabled", width=110, anchor="center")
        self.tree.column("sync", width=220, anchor="center")
        self.tree.column("source", width=130, anchor="center")
        self.tree.column("cron_expr", width=450, anchor="w")
        self.tree.column("command", width=1600, anchor="w")
        self.tree.column("description", width=600, anchor="w")
        self.tree.column("category", width=250, anchor="center")
        self.tree.column("tags", width=400, anchor="center")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", self.on_double_click)

        self.tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        vsb.pack(side="left", fill="y", padx=(0,8), pady=6)

        # Row tags (colors)
        self.tree.tag_configure("sync_ok", foreground="#1e7f1e")       # green
        self.tree.tag_configure("sync_pending", foreground="#b8860b")  # dark goldenrod
        self.tree.tag_configure("sync_diff", foreground="#cc7a00")     # orange-ish
        self.tree.tag_configure("sync_orphan", foreground="#b00020")   # red
        self.tree.tag_configure("external", foreground="gray45")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(0,6))

        if not cron_available():
            messagebox.showerror(APP_NAME, "The 'crontab' command is not available. Please install cron.")
        self.reload_from_cron()

    # ----- Preferences -----
    def open_prefs(self):
        dlg = PrefsDialog(self, self.prefs)
        self.wait_window(dlg)
        if dlg.result:
            self.prefs.update(dlg.result)
            save_prefs(self.prefs)
            # Apply immediately
            self.tk.call('tk', 'scaling', self.prefs["scaling"])
            self.geometry(f"{self.prefs['width']}x{self.prefs['height']}")
            messagebox.showinfo(APP_NAME, "Preferences applied. Some UI elements may need a restart to fully rescale.")

    # ----- Helpers -----
    def selected_item_info(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        vals = self.tree.item(iid, "values")
        # values: (id, En, Sync, Src, expr, cmd, desc, cat, tags)
        d = {
            "id": None if vals[0] in ("", "None", "—") else int(vals[0]),
            "enabled": (vals[1] == "ON"),
            "sync": vals[2],
            "source": vals[3],
            "cron_expr": vals[4],
            "command": vals[5],
            "description": vals[6],
            "category": vals[7],
            "tags": vals[8],
            "iid": iid
        }
        return d

    def _compute_ccm_map_from_crontab(self):
        """Build id -> (enabled, expr, command) from crontab CCM block."""
        text = read_crontab_text()
        prefix, ccm, suffix = split_crontab_sections(text)
        parsed_ccm = parse_ccm_block(ccm)
        m = {}
        for jid, en, expr, cmd in parsed_ccm:
            m[jid] = (bool(en), expr, cmd)
        return m, prefix, ccm, suffix

    def _sync_status_for_job(self, row):
        """Return (label, tag) for a DB row based on ccm_cron_map comparison."""
        jid = row["id"]
        db_tuple = (bool(row["enabled"]), row["cron_expr"], row["command"])
        cr = self.ccm_cron_map.get(jid)
        if cr is None:
            # Not present in crontab CCM block → Pending
            return ("🟡 Pending", "sync_pending")
        if cr == db_tuple:
            return ("✅ In Sync", "sync_ok")
        return ("⚠️ Differs", "sync_diff")

    def refresh_table(self):
        # Clear rows
        for i in self.tree.get_children():
            self.tree.delete(i)

        # DB rows (CCM)
        ccm_rows = db_get_all(self.conn)

        # Search term
        search_term = self.var_search.get().strip().lower() if hasattr(self, "var_search") else ""
        def match_filter(row):
            if not search_term:
                return True
            combined = " ".join([
                str(row.get("cron_expr", "")),
                str(row.get("command", "")),
                str(row.get("description", "")),
                str(row.get("category", "")),
                str(row.get("tags", ""))
            ]).lower()
            return search_term in combined

        # Insert CCM rows with Sync status
        for r in ccm_rows:
            if not match_filter(r):
                continue
            label, tag = self._sync_status_for_job(r)
            self.tree.insert("", "end", iid=f"CCM-{r['id']}", values=(
                r["id"],
                "ON" if r["enabled"] else "OFF",
                label,
                "CCM",
                r["cron_expr"],
                r["command"],
                r.get("description") or "",
                r.get("category") or "",
                r.get("tags") or "",
            ), tags=(tag,))

        # Insert External rows (unmanaged)
        for i, r in enumerate(self.external_rows, 1):
            if not match_filter(r):
                continue
            tags = ["external"]
            # If we created special "orphan" rows, use red tag.
            if r.get("special_sync") == "orphan":
                tags = ["sync_orphan"]
            self.tree.insert("", "end", iid=f"EXT-{i}", values=(
                "—",
                "ON" if r["enabled"] else "OFF",
                r.get("sync_label", "") or ("🔴 Orphan" if r.get("special_sync")=="orphan" else ""),
                r.get("source","External"),
                r["cron_expr"], r["command"],
                r.get("description") or "",
                r.get("category") or "",
                r.get("tags") or "",
            ), tags=tuple(tags))

        self.status.set(f"{len(ccm_rows)} CCM jobs; {len(self.external_rows)} External jobs.")

    # ----- CRUD (CCM only) -----
    def add_job(self):
        dlg = JobDialog(self, "Add Cron Job")
        self.wait_window(dlg)
        if dlg.result:
            jid = db_upsert_job(self.conn, dlg.result)
            # Mark as pending until apply
            self.reload_from_cron()  # recompute maps + refresh

    def edit_job(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to edit.")
            return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Edit with 'crontab -e'.")
            return
        current = db_get_by_id(self.conn, info["id"])
        if not current:
            messagebox.showwarning(APP_NAME, "Job not found.")
            return
        dlg = JobDialog(self, f"Edit Job #{info['id']}", current)
        self.wait_window(dlg)
        if dlg.result:
            dlg.result["id"] = info["id"]
            db_upsert_job(self.conn, dlg.result)
            self.reload_from_cron()

    def delete_job(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to delete.")
            return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Delete with 'crontab -e'.")
            return
        if not messagebox.askyesno(APP_NAME, f"Delete CCM job #{info['id']}?"):
            return
        db_delete_job(self.conn, info["id"])
        self.reload_from_cron()

    def toggle_enable(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to toggle.")
            return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Toggle via 'crontab -e'.")
            return
        rec = db_get_by_id(self.conn, info["id"])
        if not rec:
            return
        rec["enabled"] = 0 if rec["enabled"] else 1
        rec["id"] = info["id"]
        db_upsert_job(self.conn, rec)
        self.reload_from_cron()

    def run_now(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to run.")
            return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Run it manually in a terminal.")
            return
        if not messagebox.askyesno(APP_NAME, f"Run now?\n\n{info['command']}"):
            return
        rc, out, err = run(["bash", "-lc", info["command"]])
        msg = f"Exit code: {rc}"
        if out.strip():
            msg += f"\n\nSTDOUT:\n{out.strip()[:2000]}"
        if err.strip():
            msg += f"\n\nSTDERR:\n{err.strip()[:2000]}"
        messagebox.showinfo(APP_NAME, msg)

    # ----- Cron sync -----
    def reload_from_cron(self):
        """
        Read crontab, parse CCM-managed + external lines,
        compute CCM id map, build 'orphan' list, refresh view.
        """
        # Build CCM map and get all lines
        ccm_map, prefix, ccm_lines, suffix = self._compute_ccm_map_from_crontab()
        self.ccm_cron_map = ccm_map

        # External (prefix + suffix)
        externals = []
        for part in (prefix, suffix):
            for line in part:
                parsed = parse_cron_line_optional(line)
                if parsed:
                    en, expr, cmd = parsed
                    externals.append({
                        "cron_expr": expr,
                        "command": cmd,
                        "enabled": en,
                        "source": "External",
                        "description": "",
                        "category": "",
                        "tags": ""
                    })

        # Detect CCM orphans: present in crontab CCM block but missing in DB
        db_ids = {r["id"] for r in db_get_all(self.conn)}
        for jid, (en, ex, cmd) in ccm_map.items():
            if jid not in db_ids:
                externals.append({
                    "cron_expr": ex,
                    "command": cmd,
                    "enabled": en,
                    "source": "CCM-Orphan",
                    "special_sync": "orphan",
                })

        self.external_rows = externals
        self.refresh_table()
        self.status.set(f"Reloaded from crontab; {len(ccm_map)} CCM lines; {len(externals)} External jobs.")

    def apply_to_cron(self):
        """
        Build a CCM block from DB rows and write it back into crontab,
        preserving unmanaged content. Backup first, then reload (which recomputes sync).
        """
        path = backup_crontab()
        current = read_crontab_text()
        prefix, _, suffix = split_crontab_sections(current)

        rows = db_get_all(self.conn)
        block = []
        for r in rows:
            block.append(f"# [CCM:id={r['id']}]")
            line = f"{r['cron_expr']} {r['command']}"
            if r["enabled"]:
                block.append(line)
            else:
                block.append(f"# {line}")

        new_text = join_crontab(prefix, block, suffix)
        rc, out, err = write_crontab_text(new_text)
        if rc == 0:
            self.reload_from_cron()
            self.status.set(f"Applied to cron. Backup saved: {os.path.basename(path)}")
            messagebox.showinfo(APP_NAME, "Crontab updated successfully.")
        else:
            self.status.set("Failed to apply crontab.")
            messagebox.showerror(APP_NAME, f"Failed to apply crontab.\n\n{err}")

    def do_backup(self):
        path = backup_crontab()
        messagebox.showinfo(APP_NAME, f"Backed up current crontab to:\n{path}")
        self.status.set(f"Backup saved: {os.path.basename(path)}")

    # ----- Raw crontab editor -----
    def edit_crontab_with_xed(self):
        try:
            subprocess.run(["bash", "-c", "EDITOR=xed crontab -e"])
            self.reload_from_cron()
            messagebox.showinfo(APP_NAME, "Your crontab changes have been applied and reloaded.")
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not open or reload crontab:\n{e}")

    # ----- Description popup -----
    def on_double_click(self, event):
        """Show a popup with full description when double-clicking a row."""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, "values")
        # Prefer fresh DB read for CCM rows to avoid truncation
        desc = ""
        if str(item).startswith("CCM-"):
            try:
                jid = int(vals[0])
                rec = db_get_by_id(self.conn, jid)
                if rec:
                    desc = rec.get("description") or ""
            except Exception:
                pass
        if not desc:
            # Fallback to tree value
            if len(vals) >= 7:
                desc = vals[6] or ""

        if not desc.strip():
            messagebox.showinfo(APP_NAME, "No description available for this job.")
            return

        win = tk.Toplevel(self)
        win.title("Full Description")
        win.geometry("1000x500")
        text = tk.Text(win, wrap="word", font=("TkDefaultFont", 12))
        text.insert("1.0", desc)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

def main():
    ensure_dirs()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
