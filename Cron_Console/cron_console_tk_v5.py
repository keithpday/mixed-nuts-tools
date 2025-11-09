#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Console Manager (CCM) — v5 (Tkinter GUI + Full Cron Integration)

Changes vs v4
-------------
• Toolbar buttons reordered for better workflow
• Spacer added between left and right button groups
• Description popup now includes scrollbar
• Window geometry scaled for 4K: 3300x1560
• Database (cron_jobs.db) sits beside this script; backups in ./backups/
• Displays ALL cron jobs: CCM-managed and External (outside CCM block)
• Preserves unmanaged crontab content; only writes CCM block

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
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

APP_NAME = "Cron Console Manager (CCM) — v5"
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
    expr = " ".join([m.group('m'), m.group('h'), m.group('dom'),
                     m.group('mon'), m.group('dow')])
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

        ttk.Label(frm, text="Description:").grid(row=5, column=0, sticky="w")
        self.txt_desc = tk.Text(frm, width=80, height=8, wrap="word")
        self.txt_desc.grid(row=6, column=0, sticky="we")
        self.txt_desc.insert("1.0", init.get("description", "") or "")

        ttk.Label(frm, text="Category:").grid(row=7, column=0, sticky="w")
        e_cat = ttk.Entry(frm, textvariable=self.var_cat, width=30)
        e_cat.grid(row=8, column=0, sticky="we")

        ttk.Label(frm, text="Tags (comma-sep):").grid(row=9, column=0, sticky="w")
        e_tags = ttk.Entry(frm, textvariable=self.var_tags, width=50)
        e_tags.grid(row=10, column=0, sticky="we")

        btns = ttk.Frame(frm)
        btns.grid(row=11, column=0, sticky="e", pady=(8,0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Save", command=self.on_save).pack(side="right")

        # --- Key bindings ---
        # Pressing Enter in Entry fields = Save
        e_expr.bind("<Return>", lambda e: self.on_save())
        e_cmd.bind("<Return>", lambda e: self.on_save())
        e_cat.bind("<Return>", lambda e: self.on_save())
        e_tags.bind("<Return>", lambda e: self.on_save())
        # Pressing Enter in Text = insert newline (default), not Save
        self.txt_desc.bind("<Return>", lambda e: None)

        self.grab_set()
        self.focus()
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

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
        self.tk.call('tk', 'scaling', 2.0)
        self.title(APP_NAME)
        self.geometry("3300x1560")

        self.conn = ensure_db()
        self.external_rows = []

        style = ttk.Style(self)
        style.configure("External.Treeview", foreground="gray40")
        style.configure("Treeview", rowheight=48)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 14, "bold"))

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=6)

        # Left-side buttons
        ttk.Button(top, text="Run Now", command=self.run_now).pack(side="left", padx=4)
        ttk.Button(top, text="Enable/Disable", command=self.toggle_enable).pack(side="left", padx=4)
        ttk.Button(top, text="Delete", command=self.delete_job).pack(side="left", padx=4)
        ttk.Button(top, text="Edit", command=self.edit_job).pack(side="left", padx=4)
        ttk.Button(top, text="Add", command=self.add_job).pack(side="left", padx=4)

        # Spacer between left/right groups
        ttk.Frame(top).pack(side="left", expand=True)

        # Right-side buttons
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
        ttk.Button(search_frame, text="Clear", command=lambda: self.var_search.set("")).pack(side="left")
        self.var_search.trace_add("write", lambda *args: self.refresh_table())

        cols = ("id", "source", "enabled", "cron_expr", "command", "description", "category", "tags")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=40)
        for c in cols:
            self.tree.heading(c, text=c.capitalize())
        self.tree.column("id", width=90, anchor="center")
        self.tree.column("source", width=130, anchor="center")
        self.tree.column("enabled", width=120, anchor="center")
        self.tree.column("cron_expr", width=450, anchor="w")
        self.tree.column("command", width=1600, anchor="w")
        self.tree.column("description", width=600, anchor="w")
        self.tree.column("category", width=250, anchor="center")
        self.tree.column("tags", width=400, anchor="center")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", self.on_double_click)

        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=6)
        vsb.pack(side="left", fill="y", padx=(0, 8), pady=6)

        self.tree.tag_configure("external", foreground="gray45")

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=8, pady=(0, 6))

        if not cron_available():
            messagebox.showerror(APP_NAME, "The 'crontab' command is not available. Please install cron.")
        self.reload_from_cron()

    # ----- Helper methods -----
    def selected_item_info(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        vals = self.tree.item(iid, "values")
        return {
            "id": None if vals[0] in ("", "None", "—") else int(vals[0]),
            "source": vals[1],
            "enabled": vals[2] == "ON",
            "cron_expr": vals[3],
            "command": vals[4],
            "description": vals[5],
            "category": vals[6],
            "tags": vals[7],
            "iid": iid
        }

    # ----- Core methods -----
    def refresh_table(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        ccm_rows = db_get_all(self.conn)
        search_term = self.var_search.get().strip().lower()
        def match_filter(row):
            if not search_term:
                return True
            combined = " ".join([str(row.get(k, "")) for k in
                                 ("cron_expr", "command", "description", "category", "tags")]).lower()
            return search_term in combined
        for r in ccm_rows:
            if not match_filter(r): continue
            self.tree.insert("", "end", iid=f"CCM-{r['id']}", values=(
                r["id"], "CCM", "ON" if r["enabled"] else "OFF",
                r["cron_expr"], r["command"], r.get("description") or "",
                r.get("category") or "", r.get("tags") or ""))
        for i, r in enumerate(self.external_rows, 1):
            if not match_filter(r): continue
            self.tree.insert("", "end", iid=f"EXT-{i}", values=(
                "—", "External", "ON" if r["enabled"] else "OFF",
                r["cron_expr"], r["command"], "", "", ""), tags=("external",))
        self.status.set(f"{len(ccm_rows)} CCM jobs; {len(self.external_rows)} External jobs.")

    def add_job(self):
        dlg = JobDialog(self, "Add Cron Job")
        self.wait_window(dlg)
        if dlg.result:
            db_upsert_job(self.conn, dlg.result)
            self.refresh_table()

    def edit_job(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to edit."); return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Edit with 'crontab -e'."); return
        current = db_get_by_id(self.conn, info["id"])
        if not current:
            messagebox.showwarning(APP_NAME, "Job not found."); return
        dlg = JobDialog(self, f"Edit Job #{info['id']}", current)
        self.wait_window(dlg)
        if dlg.result:
            dlg.result["id"] = info["id"]
            db_upsert_job(self.conn, dlg.result)
            self.refresh_table()

    def delete_job(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to delete."); return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Delete with 'crontab -e'."); return
        if not messagebox.askyesno(APP_NAME, f"Delete CCM job #{info['id']}?"): return
        db_delete_job(self.conn, info["id"])
        self.refresh_table()

    def toggle_enable(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to toggle."); return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Toggle via 'crontab -e'."); return
        rec = db_get_by_id(self.conn, info["id"])
        if not rec: return
        rec["enabled"] = 0 if rec["enabled"] else 1
        rec["id"] = info["id"]
        db_upsert_job(self.conn, rec)
        self.refresh_table()

    def run_now(self):
        info = self.selected_item_info()
        if not info:
            messagebox.showinfo(APP_NAME, "Select a job to run."); return
        if info["source"] != "CCM":
            messagebox.showinfo(APP_NAME, "External job is read-only. Run manually."); return
        if not messagebox.askyesno(APP_NAME, f"Run now?\n\n{info['command']}"): return
        rc, out, err = run(["bash", "-lc", info["command"]])
        msg = f"Exit code: {rc}"
        if out.strip(): msg += f"\n\nSTDOUT:\n{out.strip()[:2000]}"
        if err.strip(): msg += f"\n\nSTDERR:\n{err.strip()[:2000]}"
        messagebox.showinfo(APP_NAME, msg)

    def reload_from_cron(self):
        text = read_crontab_text()
        prefix, ccm, suffix = split_crontab_sections(text)
        parsed_ccm = parse_ccm_block(ccm)
        for jid, enabled, expr, cmd in parsed_ccm:
            rec = db_get_by_id(self.conn, jid)
            if rec:
                rec.update({"cron_expr": expr, "command": cmd, "enabled": int(enabled)})
                db_upsert_job(self.conn, rec)
            else:
                db_upsert_job(self.conn, {"cron_expr": expr, "command": cmd,
                                          "enabled": int(enabled), "description": None,
                                          "category": None, "tags": None})
        externals = []
        for part in (prefix, suffix):
            for line in part:
                parsed = parse_cron_line_optional(line)
                if parsed:
                    en, expr, cmd = parsed
                    externals.append({"cron_expr": expr, "command": cmd,
                                      "enabled": en, "source": "External"})
        self.external_rows = externals
        self.refresh_table()
        self.status.set(f"Reloaded from crontab; {len(parsed_ccm)} CCM; {len(externals)} External.")

    def apply_to_cron(self):
        path = backup_crontab()
        current = read_crontab_text()
        prefix, _, suffix = split_crontab_sections(current)
        rows = db_get_all(self.conn)
        block = []
        for r in rows:
            block.append(f"# [CCM:id={r['id']}]")
            line = f"{r['cron_expr']} {r['command']}"
            block.append(line if r["enabled"] else f"# {line}")
        new_text = join_crontab(prefix, block, suffix)
        rc, _, err = write_crontab_text(new_text)
        if rc == 0:
            self.status.set(f"Applied to cron. Backup: {os.path.basename(path)}")
            messagebox.showinfo(APP_NAME, "Crontab updated successfully.")
        else:
            messagebox.showerror(APP_NAME, f"Failed to apply crontab:\n{err}")

    def do_backup(self):
        path = backup_crontab()
        messagebox.showinfo(APP_NAME, f"Backed up crontab to:\n{path}")
        self.status.set(f"Backup saved: {os.path.basename(path)}")

    def edit_crontab_with_xed(self):
        try:
            subprocess.run(["bash", "-c", "EDITOR=xed crontab -e"])
            self.reload_from_cron()
            messagebox.showinfo("Crontab Updated",
                                "Your crontab changes have been reloaded.")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open or reload crontab:\n{e}")

    def on_double_click(self, event):
        """Show a popup with full description and scrollbar."""
        item = self.tree.identify_row(event.y)
        if not item: return
        vals = self.tree.item(item, "values")
        desc = vals[5].strip() if len(vals) >= 6 else ""
        if not desc:
            messagebox.showinfo(APP_NAME, "No description available for this job.")
            return
        win = tk.Toplevel(self)
        win.title("Full Description")
        win.geometry("1000x500")
        text = tk.Text(win, wrap="word", font=("TkDefaultFont", 12))
        text.insert("1.0", desc)
        text.configure(state="disabled")
        text.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        scroll = ttk.Scrollbar(win, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=6)

def main():
    ensure_dirs()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
