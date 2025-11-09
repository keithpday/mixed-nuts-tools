#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Console Manager (CCM) — v6 (Polished UI Edition)

What's new vs v4/v5
-------------------
• Column order: ID | En | Src | Cron Expr | Command | Description | Category | Tags
• Color cues:
    - External rows are dimmed (gray) + italic
    - Enabled state: entire row green (ON) / red (OFF) for quick scanning
• Row height tightened to 40; description shows only the first line
• Double-click a row to view the full (multiline) Description in a popup
• Case-insensitive partial search across all columns with live match count
• Safer Job editor:
    - Multiline Description (8 lines)
    - Enter won't close the dialog; use Ctrl+Enter to Save, Esc to Cancel
• Tool buttons (left→right): Run Now, Enable/Disable, Delete, Edit, Add | Backup, Apply, Edit (xed), Reload
• 4K-friendly scaling and geometry maintained
"""

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox
import tkinter.font as tkfont

APP_NAME = "Cron Console Manager (CCM)"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = SCRIPT_DIR
DB_PATH = os.path.join(BASE_DIR, "cron_jobs.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

CCM_BEGIN = "# ==== CCM BEGIN ===="
CCM_END   = "# ==== CCM END ===="
CCM_MARKER_RE = re.compile(r"^#\s*\[CCM:id=(\d+)\]\s*$")

# ---------- Utilities ----------
def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)

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

def first_line(text, max_chars=120):
    """Return only first line (strip newlines), trimmed to max_chars with ellipsis."""
    if not text:
        return ""
    s = text.splitlines()[0]
    s = s.strip()
    if len(s) > max_chars:
        return s[: max_chars - 1] + "…"
    return s

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
        e_expr = ttk.Entry(frm, textvariable=self.var_expr, width=50)
        e_expr.grid(row=1, column=0, sticky="we")

        ttk.Label(frm, text="Command:").grid(row=2, column=0, sticky="w")
        e_cmd = ttk.Entry(frm, textvariable=self.var_cmd, width=80)
        e_cmd.grid(row=3, column=0, sticky="we")

        ttk.Checkbutton(frm, text="Enabled", variable=self.var_en).grid(row=4, column=0, sticky="w")

        ttk.Label(frm, text="Description (multiline, Ctrl+Enter = Save):").grid(row=5, column=0, sticky="w")
        self.txt_desc = tk.Text(frm, width=80, height=8, wrap="word")
        self.txt_desc.grid(row=6, column=0, sticky="we")
        self.txt_desc.insert("1.0", init.get("description", "") or "")

        ttk.Label(frm, text="Category:").grid(row=7, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cat, width=30).grid(row=8, column=0, sticky="we")

        ttk.Label(frm, text="Tags (comma-sep):").grid(row=9, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_tags, width=50).grid(row=10, column=0, sticky="we")

        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, sticky="e", pady=(8,0))
        ttk.Button(btns, text="Cancel (Esc)", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save (Ctrl+Enter)", command=self.on_save).pack(side="right")

        # Key bindings:
        # - Do NOT bind plain <Return> globally; it interferes with Text line breaks.
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind_all("<Control-Return>", lambda e: self.on_save())

        # Keep focus on first field
        e_expr.focus_set()

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

# ---------- App ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        # --- Global scaling for 4K monitors ---
        self.tk.call('tk', 'scaling', 2.0)

        self.title(APP_NAME)
        self.geometry("3300x1560")

        self.conn = ensure_db()
        self.external_rows = []  # list of dicts (id=None, cron_expr, command, enabled, source='External')

        # Styles & fonts
        self.style = ttk.Style(self)
        self.style.configure("Treeview", rowheight=40)
        self.style.configure("Treeview.Heading", font=("TkDefaultFont", 14, "bold"))
        # Named fonts for tagging
        self.font_normal = tkfont.nametofont("TkDefaultFont")
        self.font_bold   = tkfont.Font(**self.font_normal.configure())
        self.font_bold.configure(weight="bold")
        self.font_italic = tkfont.Font(**self.font_normal.configure())
        self.font_italic.configure(slant="italic")

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        # Left cluster
        ttk.Button(top, text="Run Now", command=self.run_now).pack(side="left", padx=4)
        ttk.Button(top, text="Enable/Disable", command=self.toggle_enable).pack(side="left", padx=4)
        ttk.Button(top, text="Delete", command=self.delete_job).pack(side="left", padx=4)
        ttk.Button(top, text="Edit", command=self.edit_job).pack(side="left", padx=4)
        ttk.Button(top, text="Add", command=self.add_job).pack(side="left", padx=4)

        # Right cluster
        ttk.Button(top, text="Backup crontab only", command=self.do_backup).pack(side="right", padx=6)
        ttk.Button(top, text="Apply CCM section to cron", command=self.apply_to_cron).pack(side="right", padx=6)
        ttk.Button(top, text="Edit crontab (xed)", command=self.edit_crontab_with_xed).pack(side="right", padx=6)
        ttk.Button(top, text="Reload from crontab", command=self.reload_from_cron).pack(side="right")

        # Search bar
        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(2, 4))
        ttk.Label(search_frame, text="Search:").pack(side="left")
        self.var_search = tk.StringVar()
        entry = ttk.Entry(search_frame, textvariable=self.var_search, width=50)
        entry.pack(side="left", padx=(4, 8), fill="x", expand=True)
        entry_font = tkfont.Font(font=entry.cget("font"))
        entry_font.configure(size=13)
        entry.configure(font=entry_font)
        ttk.Button(search_frame, text="Clear", command=lambda: self.var_search.set("")).pack(side="left")
        self.var_search.trace_add("write", lambda *args: self.refresh_table())

        # Columns (ID | En | Src | Cron Expr | Command | Description | Category | Tags)
        cols = ("id","enabled","source","cron_expr","command","description","category","tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=40)
        self.tree.heading("id", text="ID")
        self.tree.heading("enabled", text="En")
        self.tree.heading("source", text="Src")
        self.tree.heading("cron_expr", text="Cron Expr")
        self.tree.heading("command", text="Command")
        self.tree.heading("description", text="Description")
        self.tree.heading("category", text="Category")
        self.tree.heading("tags", text="Tags")

        # Widths & alignment
        self.tree.column("id", width=90, anchor="center")
        self.tree.column("enabled", width=100, anchor="center")
        self.tree.column("source", width=110, anchor="center")
        self.tree.column("cron_expr", width=460, anchor="w")
        self.tree.column("command", width=1600, anchor="w")
        self.tree.column("description", width=640, anchor="w")
        self.tree.column("category", width=260, anchor="center")
        self.tree.column("tags", width=420, anchor="center")

        # Scrollbar
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        vsb.pack(side="left", fill="y", padx=(0,8), pady=6)

        # Tags: external dim; enabled on/off colors
        self.tree.tag_configure("external", foreground="#6f6f6f", font=self.font_italic)
        self.tree.tag_configure("en_on", foreground="#007f00", font=self.font_bold)   # green-ish
        self.tree.tag_configure("en_off", foreground="#b00000", font=self.font_bold)  # red-ish

        # Status
        self.status = tk.StringVar(value="Ready.")
        lbl_status = ttk.Label(self, textvariable=self.status, anchor="w")
        lbl_status.pack(fill="x", padx=8, pady=(0,6))
        lbl_status.configure(foreground="#1E3A5F")

        if not cron_available():
            messagebox.showerror(APP_NAME, "The 'crontab' command is not available. Please install cron.")
        self.reload_from_cron()

    # ----- Helpers -----
    def selected_item_info(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        vals = self.tree.item(iid, "values")
        # values: (id, enabled, source, cron_expr, command, description, category, tags)
        d = {
            "id": None if vals[0] in ("", "None", "—") else int(vals[0]),
            "enabled": (vals[1] == "ON"),
            "source": vals[2],
            "cron_expr": vals[3],
            "command": vals[4],
            "description": vals[5],
            "category": vals[6],
            "tags": vals[7],
            "iid": iid
        }
        return d

    def _filtered_rows(self, rows):
        term = self.var_search.get().strip().lower()
        if not term:
            return rows
        out = []
        for r in rows:
            combined = " ".join([
                str(r.get("id","")),
                "ON" if r.get("enabled") else "OFF",
                str(r.get("source","")),
                str(r.get("cron_expr","")),
                str(r.get("command","")),
                str(r.get("description","")),
                str(r.get("category","")),
                str(r.get("tags",""))
            ]).lower()
            if term in combined:
                out.append(r)
        return out

    def refresh_table(self):
        # Collect rows
        ccm_rows = db_get_all(self.conn)
        ccm_rows = [{
            "id": r["id"],
            "source": "CCM",
            "enabled": bool(r["enabled"]),
            "cron_expr": r["cron_expr"],
            "command": r["command"],
            "description": r.get("description") or "",
            "category": r.get("category") or "",
            "tags": r.get("tags") or "",
        } for r in ccm_rows]

        external = self.external_rows

        # Apply search filter
        ccm_f = self._filtered_rows(ccm_rows)
        ext_f = self._filtered_rows(external)

        # Clear tree
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Insert CCM first
        for r in ccm_f:
            iid = f"CCM-{r['id']}"
            tags = []
            tags.append("en_on" if r["enabled"] else "en_off")
            self.tree.insert(
                "", "end", iid=iid,
                values=(
                    r["id"],
                    "ON" if r["enabled"] else "OFF",
                    "CCM",
                    r["cron_expr"],
                    r["command"],
                    first_line(r["description"]),
                    r["category"],
                    r["tags"]
                ),
                tags=tuple(tags)
            )

        # Insert External
        for i, r in enumerate(ext_f, 1):
            iid = f"EXT-{i}"
            tags = ["external"]
            # also color by enabled state for quick read
            tags.append("en_on" if r["enabled"] else "en_off")
            self.tree.insert(
                "", "end", iid=iid,
                values=(
                    "—",
                    "ON" if r["enabled"] else "OFF",
                    "External",
                    r["cron_expr"],
                    r["command"],
                    first_line(r.get("description","")),
                    r.get("category",""),
                    r.get("tags","")
                ),
                tags=tuple(tags)
            )

        # Status with counts
        total = len(ccm_rows) + len(external)
        shown = len(ccm_f) + len(ext_f)
        term = self.var_search.get().strip()
        if term:
            self.status.set(f"{shown}/{total} jobs match “{term}”.")
        else:
            self.status.set(f"{len(ccm_rows)} CCM jobs; {len(external)} External jobs.")

    # ----- CRUD (CCM only) -----
    def add_job(self):
        dlg = JobDialog(self, "Add Cron Job")
        self.wait_window(dlg)
        if dlg.result:
            db_upsert_job(self.conn, dlg.result)
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
            msg += f"\n\nSTDOUT:\n{out.strip()[:2000]}"
        if err.strip():
            msg += f"\n\nSTDERR:\n{err.strip()[:2000]}"
        messagebox.showinfo(APP_NAME, msg)

    # ----- Cron sync -----
    def reload_from_cron(self):
        """
        Read crontab, parse both CCM-managed and external lines.
        • CCM jobs are merged into DB (metadata preserved)
        • External jobs are shown read-only (not inserted to DB)
        """
        text = read_crontab_text()
        prefix, ccm, suffix = split_crontab_sections(text)

        # Parse CCM
        parsed_ccm = parse_ccm_block(ccm)
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
        self.refresh_table()
        self.status.set(f"Reloaded from crontab; {len(parsed_ccm)} CCM jobs; {len(externals)} External jobs.")

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
            messagebox.showinfo(
                "Crontab Updated",
                "Your crontab changes have been applied and reloaded into the console."
            )
        except Exception as e:
            messagebox.showerror("Error", f"Could not open or reload crontab:\n{e}")

    # ----- UI: description popup -----
    def on_double_click(self, event):
        """Show a popup with the full description when double-clicking a row."""
        item = self.tree.identify_row(event.y)
        if not item:
            return
        vals = self.tree.item(item, "values")
        if len(vals) < 6:
            return

        job_id = vals[0]
        source = vals[2]

        full_desc = ""
        if source == "CCM" and job_id not in ("—", "", "None"):
            # Pull full description from the database
            rec = db_get_by_id(self.conn, int(job_id))
            if rec and rec.get("description"):
                full_desc = rec["description"]
        else:
            # External job — use whatever is in the table
            full_desc = str(vals[5]).strip()

        if not full_desc:
            messagebox.showinfo(APP_NAME, "No description available for this job.")
            return

        # Popup with the full text
        win = tk.Toplevel(self)
        win.title("Full Description")
        win.geometry("1000x500")
        text = tk.Text(win, wrap="word", font=("TkDefaultFont", 12))
        text.insert("1.0", full_desc)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)


def main():
    ensure_dirs()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
