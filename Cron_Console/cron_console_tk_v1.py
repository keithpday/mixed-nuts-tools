#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Console Manager (CCM) — Path A (Tkinter, lightweight)

Features
--------
• Lists cron jobs in a Tkinter table (Treeview)
• Add / Edit / Delete / Enable / Disable jobs
• Stores rich metadata in SQLite: description, category, tags
• Uses native cron as the execution engine
• Preserves non-CCM crontab content; manages its own CCM section
• Backs up crontab before write to ~/.cron_console/backups/
• 'Run Now' to execute a job’s command immediately (shell)

Schema
------
~/.cron_console/cron_jobs.db

CREATE TABLE jobs (
  id INTEGER PRIMARY KEY,
  cron_expr TEXT NOT NULL,   -- e.g., "0 */4 * * *"
  command   TEXT NOT NULL,   -- shell command
  enabled   INTEGER NOT NULL DEFAULT 1,
  description TEXT,
  category    TEXT,
  tags        TEXT,
  created_at  TEXT DEFAULT (datetime('now')),
  updated_at  TEXT DEFAULT (datetime('now'))
);

Managed Crontab Section
-----------------------
# ==== CCM BEGIN ====
# [CCM:id=123]
0 */4 * * * /path/to/script.sh
# [CCM:id=124]
15 9 * * * /path/to/other.sh
# ==== CCM END ====

All content outside this section is preserved verbatim.

Requirements
------------
• Linux with cron installed
• Python 3.9+
"""

import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

APP_NAME = "Cron Console Manager (CCM)"
HOME = os.path.expanduser("~")
BASE_DIR = os.path.join(HOME, ".cron_console")
DB_PATH = os.path.join(BASE_DIR, "cron_jobs.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")

CCM_BEGIN = "# ==== CCM BEGIN ===="
CCM_END   = "# ==== CCM END ===="
CCM_MARKER_RE = re.compile(r"^#\s*\[CCM:id=(\d+)\]\s*$")

# --------- Utilities ---------
def ensure_dirs():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def run(cmd, input_text=None):
    """Run command, return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, input=input_text, text=True,
            capture_output=True, check=False
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"Command not found: {' '.join(cmd)}"

def cron_available():
    rc, *_ = run(["crontab", "-l"])
    # If the user has no crontab, rc could be 1 but crontab still exists.
    # Check presence of crontab binary instead:
    rc2, *_ = run(["which", "crontab"])
    return rc2 == 0

def backup_crontab():
    rc, out, err = run(["crontab", "-l"])
    # Even with rc=1 (no crontab for user), we still back up what's there (may be empty)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, f"crontab-{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        if rc == 0:
            f.write(out)
        else:
            # no crontab case
            f.write("")
    return path

def read_crontab_text():
    rc, out, err = run(["crontab", "-l"])
    if rc == 0:
        return out
    else:
        # If user has no crontab, treat as empty
        return ""

def write_crontab_text(text):
    return run(["crontab", "-"], input_text=text)

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
    out_text = "\n".join(out).rstrip() + "\n"
    return out_text

def is_cron_expr_valid(expr):
    """
    Basic 5-field cron validator.
    Accepts numbers, '*', '*/n', ranges, lists, and '@reboot' (passes through).
    """
    expr = expr.strip()
    if expr.startswith("@"):
        # allow @reboot, @daily, etc.
        allowed = {"@reboot","@yearly","@annually","@monthly","@weekly","@daily","@hourly"}
        return expr in allowed
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
            # split into expr + command
            parts = raw.split(None, 5)  # 5 splits: 5 cron fields + rest
            if len(parts) >= 6:
                expr = " ".join(parts[:5])
                command = parts[5]
                result.append((jid, enabled, expr, command))
                i += 2
                continue
        i += 1
    return result

# --------- SQLite ----------
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
    """
    job = dict(id?, cron_expr, command, enabled, description, category, tags)
    returns id
    """
    if job.get("id"):
        conn.execute("""
            UPDATE jobs SET cron_expr=?, command=?, enabled=?, description=?, category=?, tags=?, updated_at=datetime('now')
            WHERE id=?
        """, (job["cron_expr"], job["command"], int(job["enabled"]), job.get("description"), job.get("category"), job.get("tags"), job["id"]))
        conn.commit()
        return job["id"]
    else:
        cur = conn.execute("""
            INSERT INTO jobs (cron_expr, command, enabled, description, category, tags)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (job["cron_expr"], job["command"], int(job["enabled"]), job.get("description"), job.get("category"), job.get("tags")))
        conn.commit()
        return cur.lastrowid

def db_delete_job(conn, job_id):
    conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    conn.commit()

def db_get_all(conn):
    cur = conn.execute("SELECT id, cron_expr, command, enabled, description, category, tags FROM jobs ORDER BY id ASC")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def db_get_by_id(conn, job_id):
    cur = conn.execute("SELECT id, cron_expr, command, enabled, description, category, tags FROM jobs WHERE id=?", (job_id,))
    r = cur.fetchone()
    if not r: return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, r))

# --------- GUI ----------
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
        self.var_desc = tk.StringVar(value=init.get("description", ""))
        self.var_cat  = tk.StringVar(value=init.get("category", ""))
        self.var_tags = tk.StringVar(value=init.get("tags", ""))

        ttk.Label(frm, text="Cron expression (5-field or @daily/@reboot):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_expr, width=40).grid(row=1, column=0, sticky="we")

        ttk.Label(frm, text="Command:").grid(row=2, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cmd, width=60).grid(row=3, column=0, sticky="we")

        ttk.Checkbutton(frm, text="Enabled", variable=self.var_en).grid(row=4, column=0, sticky="w")

        ttk.Label(frm, text="Description:").grid(row=5, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_desc, width=60).grid(row=6, column=0, sticky="we")

        ttk.Label(frm, text="Category:").grid(row=7, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_cat, width=30).grid(row=8, column=0, sticky="we")

        ttk.Label(frm, text="Tags (comma-sep):").grid(row=9, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_tags, width=40).grid(row=10, column=0, sticky="we")

        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, sticky="e", pady=(8,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        self.bind("<Return>", lambda e: self.on_save())
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
            "description": self.var_desc.get().strip() or None,
            "category": self.var_cat.get().strip() or None,
            "tags": self.var_tags.get().strip() or None,
        }
        self.destroy()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1100x520")
        self.conn = ensure_db()

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        ttk.Button(top, text="Reload from system crontab", command=self.reload_from_cron).pack(side="left")
        ttk.Button(top, text="Apply CCM section to cron", command=self.apply_to_cron).pack(side="left", padx=6)
        ttk.Button(top, text="Backup crontab only", command=self.do_backup).pack(side="left", padx=6)

        ttk.Button(top, text="Add", command=self.add_job).pack(side="right")
        ttk.Button(top, text="Edit", command=self.edit_job).pack(side="right", padx=4)
        ttk.Button(top, text="Delete", command=self.delete_job).pack(side="right", padx=4)
        ttk.Button(top, text="Enable/Disable", command=self.toggle_enable).pack(side="right", padx=4)
        ttk.Button(top, text="Run Now", command=self.run_now).pack(side="right", padx=4)

        cols = ("id","enabled","cron_expr","command","description","category","tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=20)
        for c in cols:
            self.tree.heading(c, text=c)
        self.tree.column("id", width=60, anchor="center")
        self.tree.column("enabled", width=90, anchor="center")
        self.tree.column("cron_expr", width=160)
        self.tree.column("command", width=360)
        self.tree.column("description", width=220)
        self.tree.column("category", width=120)
        self.tree.column("tags", width=160)

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)

        self.tree.pack(side="left", fill="both", expand=True, padx=(8,0), pady=6)
        vsb.pack(side="left", fill="y", padx=(0,8), pady=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(0,6))

        if not cron_available():
            messagebox.showerror(APP_NAME, "The 'crontab' command is not available.\nPlease install cron.")
        self.refresh_table()

    # ----- Data / UI helpers -----
    def refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        rows = db_get_all(self.conn)
        for r in rows:
            self.tree.insert("", "end", iid=str(r["id"]), values=(
                r["id"],
                "ON" if r["enabled"] else "OFF",
                r["cron_expr"],
                r["command"],
                r.get("description") or "",
                r.get("category") or "",
                r.get("tags") or "",
            ))
        self.status.set(f"{len(rows)} CCM jobs loaded.")

    def selected_id(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    # ----- CRUD -----
    def add_job(self):
        dlg = JobDialog(self, "Add Cron Job")
        self.wait_window(dlg)
        if dlg.result:
            jid = db_upsert_job(self.conn, dlg.result)
            self.refresh_table()

    def edit_job(self):
        jid = self.selected_id()
        if not jid:
            messagebox.showinfo(APP_NAME, "Select a job to edit.")
            return
        current = db_get_by_id(self.conn, jid)
        if not current:
            messagebox.showwarning(APP_NAME, "Job not found.")
            return
        dlg = JobDialog(self, f"Edit Job #{jid}", current)
        self.wait_window(dlg)
        if dlg.result:
            dlg.result["id"] = jid
            db_upsert_job(self.conn, dlg.result)
            self.refresh_table()

    def delete_job(self):
        jid = self.selected_id()
        if not jid:
            messagebox.showinfo(APP_NAME, "Select a job to delete.")
            return
        if not messagebox.askyesno(APP_NAME, f"Delete job #{jid}?"):
            return
        db_delete_job(self.conn, jid)
        self.refresh_table()

    def toggle_enable(self):
        jid = self.selected_id()
        if not jid:
            messagebox.showinfo(APP_NAME, "Select a job to toggle.")
            return
        job = db_get_by_id(self.conn, jid)
        if not job:
            return
        job["enabled"] = 0 if job["enabled"] else 1
        job["id"] = jid
        db_upsert_job(self.conn, job)
        self.refresh_table()

    def run_now(self):
        jid = self.selected_id()
        if not jid:
            messagebox.showinfo(APP_NAME, "Select a job to run.")
            return
        job = db_get_by_id(self.conn, jid)
        if not job:
            return
        if not messagebox.askyesno(APP_NAME, f"Run now?\n\n{job['command']}"):
            return
        # run via shell to honor pipes, redirects, etc.
        rc, out, err = run(["bash", "-lc", job["command"]])
        msg = f"Exit code: {rc}"
        if out.strip():
            msg += f"\n\nSTDOUT:\n{out.strip()[:2000]}"
        if err.strip():
            msg += f"\n\nSTDERR:\n{err.strip()[:2000]}"
        messagebox.showinfo(APP_NAME, msg)

    # ----- Cron sync -----
    def reload_from_cron(self):
        """
        Read system crontab, parse CCM section, merge into DB.
        • Existing CCM jobs (by id) get their cron_expr/command/enabled refreshed.
        • New CCM ids get inserted if missing.
        • Unmanaged lines are ignored (we don't import them silently).
        """
        text = read_crontab_text()
        prefix, ccm, suffix = split_crontab_sections(text)
        parsed = parse_ccm_block(ccm)

        # Merge into DB
        existing = {r["id"]: r for r in db_get_all(self.conn)}
        seen_ids = set()

        for jid, enabled, expr, cmd in parsed:
            seen_ids.add(jid)
            rec = db_get_by_id(self.conn, jid)
            if rec:
                # update expr/command/enabled only; keep metadata
                rec["cron_expr"] = expr
                rec["command"] = cmd
                rec["enabled"] = 1 if enabled else 0
                rec["id"] = jid
                db_upsert_job(self.conn, rec)
            else:
                # new to DB, insert with blank metadata
                db_upsert_job(self.conn, {
                    "cron_expr": expr,
                    "command": cmd,
                    "enabled": 1 if enabled else 0,
                    "description": None, "category": None, "tags": None
                })

        # (We do NOT delete DB records that aren't in crontab; they just won't run until applied.)
        self.refresh_table()
        self.status.set(f"Reloaded from crontab; {len(parsed)} CCM jobs found.")

    def apply_to_cron(self):
        """
        Build CCM block from DB rows and write it back into crontab,
        preserving unmanaged content. Backup first.
        """
        # Backup
        path = backup_crontab()

        # Read current crontab and strip CCM block
        current = read_crontab_text()
        prefix, _, suffix = split_crontab_sections(current)

        # Build new CCM block
        rows = db_get_all(self.conn)
        block = []
        for r in rows:
            block.append(f"# [CCM:id={r['id']}]")
            line = f"{r['cron_expr']} {r['command']}"
            if r["enabled"]:
                block.append(line)
            else:
                block.append(f"# {line}")

        # Join and write
        new_text = join_crontab(prefix, block, suffix)
        rc, out, err = write_crontab_text(new_text)
        if rc == 0:
            self.status.set(f"Applied to cron successfully. Backup saved: {os.path.basename(path)}")
            messagebox.showinfo(APP_NAME, "Crontab updated successfully.")
        else:
            self.status.set("Failed to apply crontab.")
            messagebox.showerror(APP_NAME, f"Failed to apply crontab.\n\n{err}")

    def do_backup(self):
        path = backup_crontab()
        messagebox.showinfo(APP_NAME, f"Backed up current crontab to:\n{path}")
        self.status.set(f"Backup saved: {os.path.basename(path)}")

def main():
    ensure_dirs()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
