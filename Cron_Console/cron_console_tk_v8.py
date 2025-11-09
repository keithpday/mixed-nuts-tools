#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Console Manager (CCM) — v9

Features
--------
• Displays ALL cron jobs: CCM-managed and External (outside CCM block)
• External jobs are read-only and greyed out
• Preferences (prefs.json): Show/Hide Sync column (more to come)
• Toolbar (left→right): Run Now · Enable/Disable · Delete · Edit · Add · Backup · Apply CCM · Edit crontab · Reload
• Right-click context menu with common actions
• Double-click: read-only popup with resizable panes (Description + Cron interpretation) + scrollbars
• Edit dialog: 8-line description, "Show Cron Expr Help" toggle, "Explain" cron button
• Case-insensitive partial search
• Color cues (enabled/disabled/external/sync), hover highlight
• Database (cron_jobs.db) sits beside this script; backups in ./backups/
• Preserves unmanaged crontab content; only writes CCM block

Requirements
------------
• Linux with cron installed
• Python 3.9+
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
import tkinter as tk
import webbrowser  # ensure this is near the top of the file
from tkinter import ttk, messagebox

APP_NAME = "Cron Console Manager (CCM)"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = SCRIPT_DIR
DB_PATH = os.path.join(BASE_DIR, "cron_jobs.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
PREFS_PATH = os.path.join(BASE_DIR, "prefs.json")

CCM_BEGIN = "# ==== CCM BEGIN ===="
CCM_END   = "# ==== CCM END ===="
CCM_MARKER_RE = re.compile(r"^#\s*\[CCM:id=(\d+)\]\s*$")

# ---------------- Preferences ----------------
DEFAULT_PREFS = {
    "show_sync_column": True
}

def load_prefs():
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT_PREFS, **data}
    except Exception:
        return DEFAULT_PREFS.copy()

def save_prefs(prefs: dict):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except Exception as e:
        messagebox.showwarning(APP_NAME, f"Could not save preferences:\n{e}")

# ---------------- Utilities ----------------
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

def parse_ccm_block(ccm_lines):
    """
    Parse CCM block into list of (id, enabled, expr, command)
    The block looks like:
      # [CCM:id=123]
      0 */4 * * * /path
    Or disabled:
      # [CCM:id=123]
      # 0 */4 * * * /path
    """
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
            if raw.startswith("@"):  # @daily / @reboot + command
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
    """
    Try to parse any cron job line (possibly commented).
    Returns:
      (enabled, expr, command) or None if not a cron line
    """
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
    # 5-field cron
    expr = " ".join([m.group('m'), m.group('h'), m.group('dom'), m.group('mon'), m.group('dow')])
    command = m.group('cmd')
    return (not commented, expr, command)

# ---------------- Cron Explanation ----------------
DOW_NAMES = {0:"Sunday",1:"Monday",2:"Tuesday",3:"Wednesday",4:"Thursday",5:"Friday",6:"Saturday"}
MONTH_NAMES = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}

def _expand_field(token, min_v, max_v):
    """Return a human-ish description of a cron field token."""
    t = token.strip()
    if t == "*":
        return "any"
    if t.startswith("*/"):
        step = t.split("/")[1]
        return f"every {step}"
    if "-" in t and "/" in t:
        rng, step = t.split("/")
        a, b = map(int, rng.split("-"))
        return f"{a}–{b} every {step}"
    if "-" in t:
        a, b = map(int, t.split("-"))
        return f"{a}–{b}"
    if "," in t:
        return ", ".join(t.split(","))
    return t

def explain_cron(expr: str) -> str:
    expr = expr.strip()
    if expr.startswith("@"):
        mapping = {
            "@reboot": "Runs once at system startup.",
            "@yearly": "Runs once a year at 00:00 on January 1.",
            "@annually": "Runs once a year at 00:00 on January 1.",
            "@monthly": "Runs once a month at 00:00 on day 1.",
            "@weekly": "Runs once a week at 00:00 on Sunday.",
            "@daily": "Runs once a day at 00:00.",
            "@hourly": "Runs once an hour at minute 0."
        }
        return mapping.get(expr, f"Alias schedule: {expr}")
    parts = expr.split()
    if len(parts) != 5:
        return "Unrecognized cron expression."
    m, h, dom, mon, dow = parts
    m_desc = _expand_field(m, 0, 59)
    h_desc = _expand_field(h, 0, 23)
    dom_desc = _expand_field(dom, 1, 31)
    mon_desc = _expand_field(mon, 1, 12)
    dow_desc = _expand_field(dow, 0, 6)

    def fmt_mon(s):
        if s == "any": return "any month"
        try:
            return ", ".join(MONTH_NAMES.get(int(x), x) for x in s.replace(" ", "").split(","))
        except: return s

    def fmt_dow(s):
        if s == "any": return "any day of week"
        try:
            return ", ".join(DOW_NAMES.get(int(x), x) for x in s.replace(" ", "").split(","))
        except: return s

    lines = []
    lines.append("Schedule breakdown:")
    lines.append(f"  • Minute: {m_desc}")
    lines.append(f"  • Hour: {h_desc}")
    lines.append(f"  • Day of month: {dom_desc}")
    lines.append(f"  • Month: {fmt_mon(mon_desc)}")
    lines.append(f"  • Day of week: {fmt_dow(dow_desc)}")
    lines.append("")
    lines.append(f"Runs at minute {m_desc} of hour {h_desc}, on day {dom_desc}, month {mon_desc}, DOW {dow_desc}.")
    return "\n".join(lines)

# ---------------- SQLite ----------------
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
    """job: dict(id?, cron_expr, command, enabled, description, category, tags) -> id"""
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

# ---------------- Dialogs ----------------
class JobDialog(tk.Toplevel):
    def __init__(self, master, title, init=None):
        super().__init__(master)
        self.title(title)
        self.resizable(True, True)
        self.result = None

        init = init or {}
        pad = {'padx': 8, 'pady': 6}

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, **pad)

        # Cheat-sheet toggle
        self.help_visible = False
        btn_help = ttk.Button(outer, text="Show Cron Expr Help ▸", command=self.toggle_help)
        btn_help.grid(row=0, column=0, sticky="w", pady=(0,4))
        self.btn_help = btn_help

        self.help_frame = ttk.LabelFrame(outer, text="Cron Field Guide")
        self.help_label = ttk.Label(
            self.help_frame,
            text=(
                "* * * * *  command to be executed\n"
                "- - - - -\n"
                "| | | | |\n"
                "| | | | +— day of week (0–6) (Sunday=0)\n"
                "| | | +--- month (1–12)\n"
                "| | +----- day of month (1–31)\n"
                "| +------- hour (0–23)\n"
                "+--------- min (0–59)\n\n"
                "Popular examples:\n"
                "  • 0 */4 * * *      → every 4 hours\n"
                "  • 0 0 * * *        → every day at midnight\n"
                "  • 30 2 * * 1-5     → weekdays at 2:30 AM\n"
                "  • */15 * * * *     → every 15 minutes\n"
                "  • 0 8 * * 1        → every Monday at 8 AM\n"
                "  • 0 9 1 * *        → the 1st of each month at 9 AM\n"
                "  • 0 12 1 1 *       → every New Year’s Day at noon\n"
                "  • 0 18 * * 5       → every Friday at 6 PM\n"
                "  • 0 6 */2 * *      → every other day at 6 AM\n"
                "  • @reboot          → once at system startup\n"
            ),
            font=("Courier New", 10),
            justify="left"
        )
        self.help_label.pack(fill="both", expand=True, padx=8, pady=6)

        # --- Add a clickable Cron primer link below the guide ---
        link = tk.Label(
            self.help_frame,
            text="🔗 Open Cron expresssion builder (cronmaker.com)",
            fg="#0033cc",
            cursor="hand2",
            font=("TkDefaultFont", 10, "underline")
        )
        link.pack(pady=(4, 6))
        link.bind("<Button-1>", lambda e: webbrowser.open_new("www.cronmaker.com"))


        frm = ttk.Frame(outer)
        frm.grid(row=1, column=0, sticky="nsew")
        outer.grid_rowconfigure(1, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self.var_expr = tk.StringVar(value=init.get("cron_expr", "0 */4 * * *"))
        self.var_cmd  = tk.StringVar(value=init.get("command", ""))
        self.var_en   = tk.BooleanVar(value=bool(init.get("enabled", True)))
        self.var_cat  = tk.StringVar(value=init.get("category", ""))
        self.var_tags = tk.StringVar(value=init.get("tags", ""))

        # Cron + Explain
        row = 0
        ttk.Label(frm, text="Cron expression:").grid(row=row, column=0, sticky="w")
        expr_row = ttk.Frame(frm)
        expr_row.grid(row=row+1, column=0, sticky="we")
        ttk.Entry(expr_row, textvariable=self.var_expr, width=50).pack(side="left", fill="x", expand=True)
        ttk.Button(expr_row, text="Explain", command=self._explain_cron_popup).pack(side="left", padx=(6,0))

        # Command
        row += 2
        ttk.Label(frm, text="Command:").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cmd, width=80).grid(row=row+1, column=0, sticky="we")

        # Enabled
        row += 2
        ttk.Checkbutton(frm, text="Enabled", variable=self.var_en).grid(row=row, column=0, sticky="w")

        # Description (multiline)
        row += 1
        ttk.Label(frm, text="Description:").grid(row=row, column=0, sticky="w")
        row += 1
        self.txt_desc = tk.Text(frm, width=80, height=8, wrap="word")
        self.txt_desc.grid(row=row, column=0, sticky="nsew")
        self.txt_desc.insert("1.0", init.get("description", "") or "")
        frm.grid_rowconfigure(row, weight=1)
        frm.grid_columnconfigure(0, weight=1)

        # Category / Tags
        row += 1
        ttk.Label(frm, text="Category:").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Entry(frm, textvariable=self.var_cat, width=30).grid(row=row, column=0, sticky="we")

        row += 1
        ttk.Label(frm, text="Tags (comma-sep):").grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Entry(frm, textvariable=self.var_tags, width=50).grid(row=row, column=0, sticky="we")

        # Buttons
        btns = ttk.Frame(outer)
        btns.grid(row=2, column=0, sticky="e", pady=(8,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        # Make Return NOT close dialog so Enter in Text works as newline:
        self.bind("<Return>", lambda e: None)

        # Modal-ish focus without forcing a "grab" (avoids 'not viewable' errors)
        self.transient(master)
        self.focus()

    def toggle_help(self):
        if self.help_visible:
            self.help_frame.grid_forget()
            self.btn_help.configure(text="Show Cron Expr Help ▸")
            self.help_visible = False
        else:
            self.help_frame.grid(row=0, column=1, sticky="nsew", padx=(8,0))
            self.help_label.pack(fill="both", expand=True, padx=8, pady=6)
            self.btn_help.configure(text="Hide Cron Expr Help ▾")
            self.help_visible = True

    def _explain_cron_popup(self):
        msg = explain_cron(self.var_expr.get().strip())
        messagebox.showinfo("Cron Explanation", msg)

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
            "description": self.txt_desc.get("1.0", "end").strip() or None,
            "category": self.var_cat.get().strip() or None,
            "tags": self.var_tags.get().strip() or None,
        }
        self.destroy()

# ---------------- App ----------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # Global scaling for 4K
        self.tk.call('tk', 'scaling', 2.0)

        self.title(APP_NAME)
        self.geometry("3300x1560")

        self.prefs = load_prefs()
        self.conn = ensure_db()
        self.external_rows = []    # parsed external cron jobs
        self.ccm_sync_map = {}     # job_id -> in-sync/out-of-sync/unknown
        self._hover_iid = None

        # ----- Menu bar (Preferences) -----
        menubar = tk.Menu(self)
        pref_menu = tk.Menu(menubar, tearoff=0)
        pref_menu.add_command(label="Preferences…", command=self.open_prefs_dialog)
        menubar.add_cascade(label="Edit", menu=pref_menu)
        self.config(menu=menubar)

        # ----- Toolbar -----
        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="Run Now ▶", command=self.run_now).pack(side="left", padx=4)
        ttk.Button(top, text="Enable/Disable", command=self.toggle_enable).pack(side="left", padx=4)
        ttk.Button(top, text="Delete 🗑️", command=self.delete_job).pack(side="left", padx=4)
        ttk.Button(top, text="Edit ✏️", command=self.edit_job).pack(side="left", padx=4)
        ttk.Button(top, text="Add ➕", command=self.add_job).pack(side="left", padx=4)
        ttk.Button(top, text="Backup crontab only", command=self.do_backup).pack(side="right", padx=6)
        ttk.Button(top, text="Apply CCM section to cron", command=self.apply_to_cron).pack(side="right", padx=6)
        ttk.Button(top, text="Edit crontab (xed)", command=self.edit_crontab_with_xed).pack(side="right", padx=6)
        ttk.Button(top, text="Reload from crontab", command=self.reload_from_cron).pack(side="right")

        # ----- Search bar -----
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.var_search = tk.StringVar()
        entry = ttk.Entry(search_frame, textvariable=self.var_search, width=50)
        entry.pack(side="left", padx=(4, 8), fill="x", expand=True)
        ttk.Button(search_frame, text="Clear", command=lambda: self.var_search.set("")).pack(side="left")
        self.var_search.trace_add("write", lambda *args: self.refresh_table())

        # ----- Treeview -----
        cols = ("id","en","src","sync","cron_expr","command","description","category","tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=40)
        for c in cols:
            self.tree.heading(c, text=c.capitalize())

        # Column widths
        self.tree.column("id", width=90, anchor="center")
        self.tree.column("en", width=100, anchor="center")
        self.tree.column("src", width=100, anchor="center")
        self.tree.column("sync", width=170, anchor="center")
        self.tree.column("cron_expr", width=470, anchor="w")
        self.tree.column("command", width=1600, anchor="w")
        self.tree.column("description", width=600, anchor="w")
        self.tree.column("category", width=250, anchor="center")
        self.tree.column("tags", width=400, anchor="center")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Button-3>", self.on_context_menu)
        self.tree.bind("<Motion>", self.on_motion_hover)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        vsb.pack(side="left", fill="y", padx=(0,8), pady=6)

        # ----- Styles & color tags -----
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=44)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 14, "bold"))

        self.tag_styles = {
            "external": dict(foreground="gray45"),
            "enabled_on": dict(foreground="#0a7f00"),
            "enabled_off": dict(foreground="#6b6b6b"),
            "unsynced": dict(foreground="#b30000"),
        }
        for tag, cfg in self.tag_styles.items():
            self._safe_tag_config(tag, **cfg)

        self.tree.tag_configure("hover", background="#eef5ff")

        # Status
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(0,6))

        # Context menu & first load
        self._create_context_menu()
        if not cron_available():
            messagebox.showerror(APP_NAME, "The 'crontab' command is not available. Please install cron.")
        self.reload_from_cron()

    # ---------- Preferences ----------
    def open_prefs_dialog(self):
        d = tk.Toplevel(self)
        d.title("Preferences")
        d.resizable(False, False)
        frm = ttk.Frame(d, padding=10)
        frm.pack(fill="both", expand=True)
        var_sync = tk.BooleanVar(value=self.prefs.get("show_sync_column", True))
        ttk.Checkbutton(frm, text="Show Sync Column", variable=var_sync).grid(row=0, column=0, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=1, column=0, sticky="e", pady=(10,0))
        ttk.Button(btns, text="Cancel", command=d.destroy).pack(side="right", padx=4)
        def _save():
            self.prefs["show_sync_column"] = bool(var_sync.get())
            save_prefs(self.prefs)
            self.update_sync_column_visibility()
            d.destroy()
        ttk.Button(btns, text="Save", command=_save).pack(side="right")

    def update_sync_column_visibility(self):
        show = self.prefs.get("show_sync_column", True)
        self.tree.column("sync", width=170 if show else 0, stretch=False)
        # (Avoid calling refresh_table here to prevent recursion loops.)

    # ---------- Helpers ----------
    def _safe_tag_config(self, tag, **kwargs):
        try:
            self.tree.tag_configure(tag, **kwargs)
        except tk.TclError:
            pass

    def selected_item_info(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        vals = self.tree.item(iid, "values")
        # values: (id, en, src, sync, cron_expr, command, description, category, tags)
        d = {
            "id": None if vals[0] in ("", "None", "—") else int(vals[0]),
            "enabled": vals[1] == "ON",
            "source": vals[2],
            "sync": vals[3],
            "cron_expr": vals[4],
            "command": vals[5],
            "description": vals[6],
            "category": vals[7],
            "tags": vals[8],
            "iid": iid
        }
        return d

    def _truncate_one_line(self, s, maxlen=110):
        s = (s or "").replace("\n", " ").strip()
        return s if len(s) <= maxlen else s[:maxlen-1] + "…"

    def refresh_table(self):
        # Clear rows
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Set sync column visibility
        self.update_sync_column_visibility()

        # Gather rows
        ccm_rows = db_get_all(self.conn)
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

        # CCM jobs
        for r in ccm_rows:
            if not match_filter(r):
                continue
            sync_state = self.ccm_sync_map.get(r["id"], "unknown")
            sync_text = {"in-sync":"✅ In Sync", "out-of-sync":"❌ Out of Sync", "unknown":"—"}.get(sync_state, "—")
            tags = []
            tags.append("enabled_on" if r["enabled"] else "enabled_off")
            if sync_state == "out-of-sync":
                tags.append("unsynced")

            self.tree.insert("", "end", iid=f"CCM-{r['id']}", values=(
                r["id"], "ON" if r["enabled"] else "OFF",
                "CCM", sync_text,
                r["cron_expr"], r["command"],
                self._truncate_one_line(r.get("description") or ""),
                r.get("category") or "",
                r.get("tags") or "",
            ), tags=tuple(tags))

        # External jobs
        for i, r in enumerate(self.external_rows, 1):
            if not match_filter(r):
                continue
            iid = f"EXT-{i}"
            self.tree.insert("", "end", iid=iid, values=(
                "—", "ON" if r["enabled"] else "OFF",
                "EXT", "—",
                r["cron_expr"], r["command"],
                self._truncate_one_line(r.get("description") or ""),
                r.get("category") or "",
                r.get("tags") or "",
            ), tags=("external",))

        self.status.set(f"{len(ccm_rows)} CCM jobs; {len(self.external_rows)} External jobs.")

    # Row hover highlight
    def on_motion_hover(self, event):
        rowid = self.tree.identify_row(event.y)
        if self._hover_iid == rowid:
            return
        # Clear previous
        if self._hover_iid is not None:
            self.tree.item(self._hover_iid, tags=[t for t in self.tree.item(self._hover_iid, "tags") if t != "hover"])
        self._hover_iid = rowid
        if rowid:
            tags = list(self.tree.item(rowid, "tags"))
            if "hover" not in tags:
                tags.append("hover")
            self.tree.tag_configure("hover", background="#eef5ff")
            self.tree.item(rowid, tags=tags)

    # ---------- Context menu setup ----------
    def _create_context_menu(self):
        """Initialize the right-click context menu."""
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Run Now ▶", command=self.run_now)
        self.menu.add_command(label="Edit ✏️", command=self.edit_job)
        self.menu.add_command(label="Enable/Disable", command=self.toggle_enable)
        self.menu.add_command(label="Delete 🗑️", command=self.delete_job)
        self.menu.add_separator()
        self.menu.add_command(label="Show Description", command=lambda: self.show_description_popup(from_menu=True))
        self.menu.add_command(label="Explain Cron Expr", command=self.explain_selected_cron)
        self.menu.add_separator()
        self.menu.add_command(label="Edit in crontab (xed)", command=self.edit_crontab_with_xed)

    # ---------- CRUD (CCM only) ----------
    def add_job(self):
        dlg = JobDialog(self, "Add Cron Job")
        self.wait_window(dlg)
        if dlg.result:
            db_upsert_job(self.conn, dlg.result)
            self._recalc_sync_against_crontab()
            self.refresh_table()

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
            self._recalc_sync_against_crontab()
            self.refresh_table()

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
        self._recalc_sync_against_crontab()
        self.refresh_table()

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
        self._recalc_sync_against_crontab()
        self.refresh_table()

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
            msg += f"\n\nSTDOUT:\n{out.strip()[:4000]}"
        if err.strip():
            msg += f"\n\nSTDERR:\n{err.strip()[:4000]}"
        messagebox.showinfo(APP_NAME, msg)

    # ---------- Cron sync ----------
    def reload_from_cron(self):
        """
        Read crontab, parse both CCM-managed and external lines.
        • CCM jobs are merged into DB (metadata preserved)
        • External jobs are shown read-only (not inserted to DB)
        • Sync status computed per CCM job
        """
        text = read_crontab_text()
        prefix, ccm, suffix = split_crontab_sections(text)

        # Parse CCM
        parsed_ccm = parse_ccm_block(ccm)  # [(id, enabled, expr, cmd)]
        ccm_map = {jid: (enabled, expr, cmd) for (jid, enabled, expr, cmd) in parsed_ccm}

        # Merge into DB
        for jid, enabled, expr, cmd in parsed_ccm:
            rec = db_get_by_id(self.conn, jid)
            if rec:
                rec["cron_expr"] = expr
                rec["command"] = cmd
                rec["enabled"] = 1 if enabled else 0
                rec["id"] = jid
                db_upsert_job(self.conn, rec)
            else:
                db_upsert_job(self.conn, {
                    "cron_expr": expr,
                    "command": cmd,
                    "enabled": 1 if enabled else 0,
                    "description": None, "category": None, "tags": None
                })

        # Parse External from prefix + suffix
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
        self.external_rows = externals

        # Compute sync map
        self._recalc_sync_against_crontab(ccm_override=ccm_map)

        self.refresh_table()
        self.status.set(f"Reloaded from crontab; {len(parsed_ccm)} CCM jobs; {len(externals)} External jobs.")

    def _recalc_sync_against_crontab(self, ccm_override=None):
        """
        For each CCM DB row, mark 'in-sync' if an identical entry exists
        in the current CCM block of crontab (id, enabled, expr, command).
        Otherwise 'out-of-sync'. If no CCM block found for that id → 'unknown'.
        """
        if ccm_override is None:
            text = read_crontab_text()
            _, ccm, _ = split_crontab_sections(text)
            parsed_ccm = parse_ccm_block(ccm)
            ccm_map = {jid: (enabled, expr, cmd) for (jid, enabled, expr, cmd) in parsed_ccm}
        else:
            ccm_map = ccm_override

        self.ccm_sync_map.clear()
        for row in db_get_all(self.conn):
            jid = row["id"]
            if jid in ccm_map:
                en2, expr2, cmd2 = ccm_map[jid]
                match = (bool(row["enabled"]) == bool(en2)
                         and (row["cron_expr"].strip() == expr2.strip())
                         and (row["command"].strip() == cmd2.strip()))
                self.ccm_sync_map[jid] = "in-sync" if match else "out-of-sync"
            else:
                self.ccm_sync_map[jid] = "unknown"

    def apply_to_cron(self):
        """
        Build a CCM block from DB rows and write it back into crontab,
        preserving unmanaged content. Backup first.
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
            self.status.set(f"Applied to cron. Backup saved: {os.path.basename(path)}")
            messagebox.showinfo(APP_NAME, "Crontab updated successfully.")
            self.reload_from_cron()
        else:
            self.status.set("Failed to apply crontab.")
            messagebox.showerror(APP_NAME, f"Failed to apply crontab.\n\n{err}")

    def do_backup(self):
        path = backup_crontab()
        messagebox.showinfo(APP_NAME, f"Backed up current crontab to:\n{path}")
        self.status.set(f"Backup saved: {os.path.basename(path)}")

    # ---------- Raw crontab editor ----------
    def edit_crontab_with_xed(self):
        try:
            subprocess.run(["bash", "-c", "EDITOR=xed crontab -e"])
            self.reload_from_cron()
            messagebox.showinfo("Crontab Updated", "Your crontab changes have been applied and reloaded into the console.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open or reload crontab:\n{e}")

    # ---------- Popups / Context ----------
    def on_double_click(self, event):
        """Show popup with full description and cron interpretation."""
        item = self.tree.identify_row(event.y)
        if not item:
            return

        vals = self.tree.item(item, "values")
        if len(vals) < 9:
            messagebox.showinfo(APP_NAME, "Incomplete row data.")
            return

        # Column order: id,en,src,sync,cron_expr,command,description,category,tags
        job_id = vals[0]
        cron_expr = vals[4]
        description = vals[6] or ""

        if not description.strip():
            description = "(No description available.)"

        # --- Create popup ---
        win = tk.Toplevel(self)
        win.title(f"Job {job_id} — Description & Cron")
        win.geometry("1100x750")
        win.transient(self)
        # Grid that expands
        for r in (0,1,2,3):
            win.grid_rowconfigure(r, weight=0)
        win.grid_rowconfigure(1, weight=1)
        win.grid_rowconfigure(3, weight=1)
        win.grid_columnconfigure(0, weight=1)

        # --- Description section ---
        ttk.Label(win, text="Description (read-only)", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 0)
        )

        desc_frame = ttk.Frame(win)
        desc_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 12))
        desc_frame.grid_columnconfigure(0, weight=1)
        desc_frame.grid_rowconfigure(0, weight=1)

        txt_desc = tk.Text(desc_frame, wrap="word", font=("TkDefaultFont", 12), padx=8, pady=8)
        txt_desc.insert("1.0", description)
        txt_desc.configure(state="disabled")
        txt_desc.grid(row=0, column=0, sticky="nsew")
        scroll1 = ttk.Scrollbar(desc_frame, orient="vertical", command=txt_desc.yview)
        txt_desc.configure(yscrollcommand=scroll1.set)
        scroll1.grid(row=0, column=1, sticky="ns")

        # --- Cron expression interpretation ---
        ttk.Label(win, text="Cron Expression Interpretation (read-only)", font=("TkDefaultFont", 11, "bold")).grid(
            row=2, column=0, sticky="w", padx=10
        )

        cron_frame = ttk.Frame(win)
        cron_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 10))
        cron_frame.grid_columnconfigure(0, weight=1)
        cron_frame.grid_rowconfigure(0, weight=1)

        txt_cron = tk.Text(cron_frame, wrap="word", font=("TkDefaultFont", 12), padx=8, pady=8)
        interpretation = explain_cron(cron_expr)
        txt_cron.insert("1.0", interpretation)
        txt_cron.configure(state="disabled")
        txt_cron.grid(row=0, column=0, sticky="nsew")
        scroll2 = ttk.Scrollbar(cron_frame, orient="vertical", command=txt_cron.yview)
        txt_cron.configure(yscrollcommand=scroll2.set)
        scroll2.grid(row=0, column=1, sticky="ns")

        ttk.Button(win, text="Close", command=win.destroy).grid(row=4, column=0, pady=8)

    def show_description_popup(self, from_menu=False):
        info = self.selected_item_info()
        if not info:
            return
        desc = (info.get("description") or "").strip()
        interp = explain_cron(info.get("cron_expr", "").strip())

        win = tk.Toplevel(self)
        win.title(f"Job #{info.get('id','—')} — Description & Cron")
        win.geometry("1200x650")

        pw = ttk.Panedwindow(win, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=10)

        topf = ttk.LabelFrame(pw, text="Description (read-only)")
        botf = ttk.LabelFrame(pw, text="Cron Expression Interpretation (read-only)")
        pw.add(topf, weight=1)
        pw.add(botf, weight=1)

        txt1 = tk.Text(topf, wrap="word", font=("TkDefaultFont", 12))
        txt1.insert("1.0", desc or "—")
        txt1.configure(state="disabled")
        sc1 = ttk.Scrollbar(topf, orient="vertical", command=txt1.yview)
        txt1.configure(yscrollcommand=sc1.set)
        txt1.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        sc1.pack(side="right", fill="y", padx=(0,8), pady=6)

        txt2 = tk.Text(botf, wrap="word", font=("TkDefaultFont", 12))
        txt2.insert("1.0", interp or "—")
        txt2.configure(state="disabled")
        sc2 = ttk.Scrollbar(botf, orient="vertical", command=txt2.yview)
        txt2.configure(yscrollcommand=sc2.set)
        txt2.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        sc2.pack(side="right", fill="y", padx=(0,8), pady=6)

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0,8))

    def on_context_menu(self, event):
        rowid = self.tree.identify_row(event.y)
        if rowid:
            self.tree.selection_set(rowid)
            info = self.selected_item_info()
            # Toggle external-only items
            self.menu.entryconfig("Edit ✏️", state="normal" if info and info["source"]=="CCM" else "disabled")
            self.menu.entryconfig("Enable/Disable", state="normal" if info and info["source"]=="CCM" else "disabled")
            self.menu.entryconfig("Delete 🗑️", state="normal" if info and info["source"]=="CCM" else "disabled")
            self.menu.entryconfig("Run Now ▶", state="normal" if info and info["source"]=="CCM" else "disabled")
            self.menu.tk_popup(event.x_root, event.y_root)

    def explain_selected_cron(self):
        info = self.selected_item_info()
        if not info:
            return
        messagebox.showinfo("Cron Explanation", explain_cron(info["cron_expr"]))

# ---------- Main ----------
def main():
    ensure_dirs()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
