#!/usr/bin/env python3
import os
import json
import sqlite3
import subprocess
import textwrap
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo  # stdlib; Python 3.9+

# ---- Adjust these if you rename things ----
DB_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/MyScheduler/myscheduler.db"
SERVICE_NAME = "myscheduler.service"  # use user-level service for no-sudo
USE_USER_SYSTEMD = False
DEFAULT_TAIL_LINES = 50

# ----------------- helpers -----------------
def pause():
    input("\nPress Enter to continue...")

def run_cmd(cmd):
    return subprocess.run(cmd, text=True, capture_output=True)

def connect_db():
    if not os.path.exists(DB_PATH):
        print(f"DB not found at {DB_PATH}.")
        return None
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=30)
        return conn
    except Exception as e:
        print("Failed to open DB:", e)
        return None

def pretty_bool(i):
    return "ON " if int(i or 0) else "OFF"

def tail_file(path, n=DEFAULT_TAIL_LINES):
    if not path:
        print("No path configured."); return
    if not os.path.exists(path):
        print(f"(no file) {path}"); return
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 8192
            data = bytearray()
            pos = size
            lines = 0
            while pos > 0 and lines <= n:
                read_size = block if pos - block > 0 else pos
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data[:0] = chunk
                lines = data.count(b"\n")
            text = data.decode("utf-8", errors="replace")
        print(f"\n--- tail -n {n} {path} ---")
        print("\n".join(text.splitlines()[-n:]))
    except Exception as e:
        print(f"Error reading {path}: {e}")

def ensure_logs_dir(path):
    if path:
        os.makedirs(os.path.dirname(path), exist_ok=True)

def ensure_replies_table(conn):
    conn.execute("""
      CREATE TABLE IF NOT EXISTS sms_replies (
        id INTEGER PRIMARY KEY,
        from_number TEXT NOT NULL,
        to_number   TEXT NOT NULL,
        body        TEXT NOT NULL,
        received_utc TEXT NOT NULL DEFAULT (datetime('now'))
      );
    """)
    conn.commit()

# --------------- systemd controls ---------------
def _svc_args(subcmd):
    base = ["systemctl"]
    if USE_USER_SYSTEMD:
        base += ["--user"]
    return base + [subcmd, SERVICE_NAME]

def svc_status():
    p = run_cmd(_svc_args("status")); print(p.stdout or p.stderr)

def svc_start():
    p = run_cmd(_svc_args("start")); print(p.stdout or f"Started {SERVICE_NAME}")

def svc_stop():
    p = run_cmd(_svc_args("stop")); print(p.stdout or f"Stopped {SERVICE_NAME}")

def svc_restart():
    p = run_cmd(_svc_args("restart")); print(p.stdout or f"Restarted {SERVICE_NAME}")

def svc_logs(n=200, follow=False):
    base = ["journalctl"]
    if USE_USER_SYSTEMD:
        base += ["--user"]
    base += ["-u", SERVICE_NAME, "--no-pager"]
    if follow:
        print("(Following logs; Ctrl+C to return)")
        try:
            subprocess.call(base + ["-f"])
        except KeyboardInterrupt:
            pass
        return
    p = run_cmd(base + [f"-n{n}"]); print(p.stdout or p.stderr)

# --------------- DB operations -----------------
def list_jobs(conn):
    cur = conn.cursor()
    cur.execute("""SELECT id, name, enabled, schedule_type, interval_seconds, cron_expr,
                          next_run_utc, run_count
                   FROM jobs ORDER BY id ASC""")
    rows = cur.fetchall()
    if not rows:
        print("No jobs found."); return
    print("\nJobs:")
    print("-"*100)
    for (jid, name, enabled, stype, interval, cron, next_run, rcnt) in rows:
        schedule = f"interval={interval}s" if stype == "interval" else f"cron='{cron}'" if stype=="cron" else "once"
        print(f"[{jid:02d}] {name:30.30s}  enabled={pretty_bool(enabled)}  type={stype:8s}  "
              f"{schedule:20s}  next={next_run or '-':20s}  runs={rcnt}")
    print("-"*100)

def show_recent_runs(conn, limit=20):
    cur = conn.cursor()
    cur.execute("""SELECT id, job_id, status, exit_code, started_utc, finished_utc
                   FROM runs ORDER BY id DESC LIMIT ?""", (limit,))
    rows = cur.fetchall()
    if not rows:
        print("No runs recorded."); return
    print("\nRecent runs:")
    print("-"*100)
    for rid, jid, status, code, started, finished in rows:
        print(f"#{rid:04d}  job={jid:02d}  {status:7s}  exit={str(code):>3s}  {started}  ->  {finished}")
    print("-"*100)

def job_details(conn, job_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    if not row:
        print(f"Job {job_id} not found."); return None
    cols = [d[0] for d in cur.description]
    d = dict(zip(cols, row))
    print("\nJob details:")
    for k in cols:
        print(f"  {k}: {d.get(k)}")
    return d

def kick_job_now(conn, job_id):
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET next_run_utc=datetime('now','-1 minute') WHERE id=?", (job_id,))
    print(f"Job {job_id} marked due now.")

def enable_job(conn, job_id, enable: bool):
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET enabled=? WHERE id=?", (1 if enable else 0, job_id))
    print(f"Job {job_id} {'ENABLED' if enable else 'DISABLED'}.")

def delete_job(conn, job_id):
    cur = conn.cursor()
    cur.execute("DELETE FROM jobs WHERE id=?", (job_id,))
    print(f"Job {job_id} deleted.")

def show_job_logs(conn, job_id, n=DEFAULT_TAIL_LINES):
    cur = conn.cursor()
    cur.execute("SELECT stdout_path, stderr_path, log_path FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    if not row:
        print(f"Job {job_id} not found."); return
    stdout_path, stderr_path, log_path = row
    if stdout_path: tail_file(stdout_path, n)
    if stderr_path: tail_file(stderr_path, n)
    if log_path and log_path not in (stdout_path, stderr_path): tail_file(log_path, n)
    if not any(row):
        print("This job has no log file paths configured (stdout_path/stderr_path/log_path).")

def add_echo_test(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM jobs WHERE name='Echo test (1m)'")
    cur.execute("""
        INSERT INTO jobs (name, program_path, args, schedule_type, interval_seconds, stdout_path)
        VALUES ('Echo test (1m)', '/bin/echo', 'Hello from scheduler', 'interval', 60,
                '/home/keith/PythonProjects/projects/Mixed_Nuts/logs/echo_test.out')
    """)
    cur.execute("UPDATE jobs SET next_run_utc=datetime('now','-1 minute') WHERE name='Echo test (1m)'")
    print("Echo test job added and scheduled immediately.")

# --------------- Interactive helpers (shared) -----------------
def _input_default(prompt, default=None):
    sfx = f" [{default}]" if default is not None else ""
    val = input(f"{prompt}{sfx}: ").strip()
    return default if (val == "" and default is not None) else val

def _yes_no(prompt, default=True):
    dv = "Y/n" if default else "y/N"
    val = input(f"{prompt} ({dv}): ").strip().lower()
    if val == "": return default
    return val in {"y","yes"}

def _nonempty(prompt, default=None):
    while True:
        v = _input_default(prompt, default)
        if v != "": return v
        print("Please enter a value.")

def _gather_job_fields_interactive(defaults=None, mode="create"):
    """
    Interactive prompts for job fields. `defaults` is a dict of existing values (for edit/copy).
    Returns a dict of fields ready to insert/update.
    """
    d = defaults or {}

    print("\n=== {} Job ===".format("Edit" if mode=="edit" else "Create/Copy"))

    name = _nonempty("Name", d.get("name", "New Job"))
    program_path = _nonempty("Program path (absolute)", d.get("program_path", "/home/keith/PythonProjects/projects/Mixed_Nuts/your_script.py"))
    args = _input_default("Args (leave blank for none)", d.get("args", "") or "")
    working_dir = _input_default("Working dir (optional)", d.get("working_dir", "") or "")
    venv_path = _input_default("Virtualenv path (optional, points to venv folder)", d.get("venv_path", "") or "")
    env_json = _input_default("Extra env vars as JSON (optional)", d.get("env_json", "") or "")

    # schedule type
    while True:
        stype = _input_default("Schedule type [cron|interval|once]", d.get("schedule_type", "interval")).lower()
        if stype in {"cron","interval","once"}: break
        print("Please enter 'cron', 'interval', or 'once'.")

    cron_expr = None
    interval_seconds = None
    once_at_utc = None
    timezone_name = _input_default("Timezone (IANA name, for cron/once)", d.get("timezone", "America/Denver"))

    if stype == "cron":
        cron_expr = _nonempty("Cron expression (e.g., 0 9 * * * for 9:00 AM daily)", d.get("cron_expr", "0 9 * * *"))
    elif stype == "interval":
        while True:
            try:
                interval_seconds = int(_nonempty("Interval seconds", str(d.get("interval_seconds", 3600))))
                if interval_seconds > 0: break
            except ValueError:
                pass
            print("Enter a positive integer.")
    else:  # once
        # Derive defaults from existing once_at_utc if present
        date_def = datetime.now().strftime("%Y-%m-%d")
        time_def = "09:00"
        if d.get("once_at_utc"):
            try:
                tz = ZoneInfo(timezone_name)
                utc_dt = datetime.fromisoformat(d["once_at_utc"])
                local_dt = utc_dt.astimezone(tz)
                date_def = local_dt.strftime("%Y-%m-%d")
                time_def = local_dt.strftime("%H:%M")
            except Exception:
                pass
        print("Enter local date/time for one-time run.")
        date_str = _nonempty("Local date (YYYY-MM-DD)", date_def)
        time_str = _nonempty("Local time (HH:MM, 24h)", time_def)
        try:
            local_dt = datetime.fromisoformat(f"{date_str} {time_str}")
            tz = ZoneInfo(timezone_name)
            local_dt = local_dt.replace(tzinfo=tz)
            once_at_utc = local_dt.astimezone(timezone.utc).isoformat()
            print(f"Will run once at (UTC): {once_at_utc}")
        except Exception as e:
            print("Could not parse date/time or timezone:", e)
            return None

    enabled = 1 if _yes_no("Enable now?", bool(d.get("enabled", 1))) else 0
    no_overlap = 1 if _yes_no("Prevent overlapping runs?", bool(d.get("no_overlap", 1))) else 0

    def as_int(default_val, prompt_txt, default_show):
        try:
            return int(_input_default(prompt_txt, str(default_show)))
        except ValueError:
            return default_val

    timeout_seconds = as_int(d.get("timeout_seconds", 0), "Timeout seconds (0 = none)", d.get("timeout_seconds", 0))
    retries = as_int(d.get("retries", 0), "Retry count on error", d.get("retries", 0))
    retry_backoff_sec = as_int(d.get("retry_backoff_sec", 60), "Retry backoff seconds", d.get("retry_backoff_sec", 60))

    # logging paths
    default_logs_dir = "/home/keith/PythonProjects/projects/Mixed_Nuts/logs"
    os.makedirs(default_logs_dir, exist_ok=True)
    want_logs = _yes_no("Configure/confirm log file paths (stdout/stderr/log)?", True)
    stdout_path = d.get("stdout_path") or ""
    stderr_path = d.get("stderr_path") or ""
    log_path    = d.get("log_path") or ""
    if want_logs:
        # default filenames derived from job name
        base = name.lower().replace(' ','_')
        stdout_path = _input_default("stdout_path", stdout_path or f"{default_logs_dir}/{base}.out")
        stderr_path = _input_default("stderr_path", stderr_path or f"{default_logs_dir}/{base}.err")
        log_path    = _input_default("log_path (optional)", log_path or f"{default_logs_dir}/{base}.log")
        ensure_logs_dir(stdout_path); ensure_logs_dir(stderr_path)
        if log_path: ensure_logs_dir(log_path)

    # normalize blanks to None for DB
    def nz(x): return x if (x is not None and str(x).strip() != "") else None

    return {
        "name": name,
        "program_path": program_path,
        "args": nz(args),
        "working_dir": nz(working_dir),
        "venv_path": nz(venv_path),
        "env_json": nz(env_json),
        "schedule_type": stype,
        "cron_expr": nz(cron_expr),
        "interval_seconds": interval_seconds,
        "once_at_utc": nz(once_at_utc),
        "timezone": timezone_name,
        "enabled": enabled,
        "no_overlap": no_overlap,
        "timeout_seconds": timeout_seconds,
        "retries": retries,
        "retry_backoff_sec": retry_backoff_sec,
        "stdout_path": nz(stdout_path),
        "stderr_path": nz(stderr_path),
        "log_path": nz(log_path),
    }

# --------------- Interactive job creation -----------------
def create_job_interactive(conn):
    fields = _gather_job_fields_interactive(None, mode="create")
    if not fields:
        print("Canceled."); return

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (
          name, program_path, args, working_dir, venv_path, env_json,
          schedule_type, cron_expr, interval_seconds, once_at_utc, timezone,
          enabled, no_overlap, timeout_seconds, retries, retry_backoff_sec,
          stdout_path, stderr_path, log_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fields["name"], fields["program_path"], fields["args"], fields["working_dir"],
        fields["venv_path"], fields["env_json"], fields["schedule_type"], fields["cron_expr"],
        fields["interval_seconds"], fields["once_at_utc"], fields["timezone"], fields["enabled"],
        fields["no_overlap"], fields["timeout_seconds"], fields["retries"], fields["retry_backoff_sec"],
        fields["stdout_path"], fields["stderr_path"], fields["log_path"]
    ))
    job_id = cur.lastrowid

    if _yes_no("Kick this job to run immediately?", False):
        cur.execute("UPDATE jobs SET next_run_utc=datetime('now','-1 minute') WHERE id=?", (job_id,))
        print(f"Job {job_id} scheduled to run now.")
    else:
        print(f"Job {job_id} created. It will appear with a next_run_utc after the scheduler's refresh.")

    print("\nCreated job:")
    job_details(conn, job_id)

# --------------- NEW: Edit existing job -----------------
def edit_job_interactive(conn):
    try:
        jid = int(input("Job ID to edit: ").strip())
    except ValueError:
        print("Invalid Job ID."); return

    current = job_details(conn, jid)
    if not current:
        return

    # Gather updates with current values as defaults
    fields = _gather_job_fields_interactive(current, mode="edit")
    if not fields:
        print("Canceled."); return

    cur = conn.cursor()
    cur.execute("""
        UPDATE jobs SET
          name=?, program_path=?, args=?, working_dir=?, venv_path=?, env_json=?,
          schedule_type=?, cron_expr=?, interval_seconds=?, once_at_utc=?, timezone=?,
          enabled=?, no_overlap=?, timeout_seconds=?, retries=?, retry_backoff_sec=?,
          stdout_path=?, stderr_path=?, log_path=?,
          next_run_utc=NULL
        WHERE id=?
    """, (
        fields["name"], fields["program_path"], fields["args"], fields["working_dir"],
        fields["venv_path"], fields["env_json"], fields["schedule_type"], fields["cron_expr"],
        fields["interval_seconds"], fields["once_at_utc"], fields["timezone"], fields["enabled"],
        fields["no_overlap"], fields["timeout_seconds"], fields["retries"], fields["retry_backoff_sec"],
        fields["stdout_path"], fields["stderr_path"], fields["log_path"],
        jid
    ))

    if _yes_no("Kick this job to run immediately?", False):
        cur.execute("UPDATE jobs SET next_run_utc=datetime('now','-1 minute') WHERE id=?", (jid,))
        print(f"Job {jid} scheduled to run now.")
    else:
        print("Updated. next_run_utc cleared; scheduler will recompute on next tick.")

    print("\nUpdated job:")
    job_details(conn, jid)

# --------------- NEW: Copy/duplicate a job -----------------
def copy_job_interactive(conn):
    try:
        src_id = int(input("Source Job ID to copy: ").strip())
    except ValueError:
        print("Invalid Job ID."); return

    src = job_details(conn, src_id)
    if not src:
        return

    # Suggest a new name
    src["name"] = f"{src.get('name','New Job')} (copy)"

    # Gather fields with source defaults
    fields = _gather_job_fields_interactive(src, mode="copy")
    if not fields:
        print("Canceled."); return

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO jobs (
          name, program_path, args, working_dir, venv_path, env_json,
          schedule_type, cron_expr, interval_seconds, once_at_utc, timezone,
          enabled, no_overlap, timeout_seconds, retries, retry_backoff_sec,
          stdout_path, stderr_path, log_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fields["name"], fields["program_path"], fields["args"], fields["working_dir"],
        fields["venv_path"], fields["env_json"], fields["schedule_type"], fields["cron_expr"],
        fields["interval_seconds"], fields["once_at_utc"], fields["timezone"], fields["enabled"],
        fields["no_overlap"], fields["timeout_seconds"], fields["retries"], fields["retry_backoff_sec"],
        fields["stdout_path"], fields["stderr_path"], fields["log_path"]
    ))
    new_id = cur.lastrowid

    if _yes_no("Kick this new job to run immediately?", False):
        cur.execute("UPDATE jobs SET next_run_utc=datetime('now','-1 minute') WHERE id=?", (new_id,))
        print(f"Job {new_id} scheduled to run now.")
    else:
        print(f"Job {new_id} created. Scheduler will compute next_run_utc on refresh.")

    print("\nNew copied job:")
    job_details(conn, new_id)

def view_sms_replies(conn, default_limit=50):
    try:
        lim = input(f"How many replies to show? (default {default_limit}): ").strip()
        limit = int(lim) if lim else default_limit
    except ValueError:
        limit = default_limit

    number_filter = input("Filter by from number (E.164, optional): ").strip()
    since_hours_s = input("Only since last N hours (optional, e.g. 24): ").strip()
    since_clause = ""
    params = []

    if number_filter:
        since_clause += " AND from_number = ?"
        params.append(number_filter)
    if since_hours_s:
        try:
            n = int(since_hours_s)
            since_clause += " AND received_utc >= datetime('now', ?)"
            params.append(f"-{n} hours")
        except ValueError:
            pass

    sql = f"""
      SELECT id, received_utc, from_number, to_number, body
      FROM sms_replies
      WHERE 1=1 {since_clause}
      ORDER BY id DESC
      LIMIT ?
    """
    params.append(limit)

    cur = conn.cursor()
    cur.execute(sql, tuple(params))
    rows = cur.fetchall()

    if not rows:
        print("No SMS replies found (for this filter).")
        return

    print("\nRecent SMS replies:")
    print("-"*100)
    for rid, ts, frm, to, body in rows:
        body_1 = body.replace("\n", " ")[:80]
        print(f"#{rid:05d}  {ts}  from {frm}  to {to}\n   {body_1}")
    print("-"*100)

# ----------------- UI -----------------
MENU = textwrap.dedent("""
    ================= Scheduler Console (my_scheduler_consoleV1.py)=================
    1) Service status
    2) Start service
    3) Stop service
    4) Restart service
    5) View service logs (last 200)
    6) Follow service logs (live; Ctrl+C to stop)

    7) List jobs
    8) Show recent runs (last 20)
    9) Job details
   10) Kick a job (run now)
   11) Enable a job
   12) Disable a job
   13) Delete a job
   14) Show job log files (tail)
   15) Add 1-minute echo test job
   16) Create a NEW job interactively
   17) View SMS replies (last 50)
   18) EDIT an existing job
   19) COPY (duplicate) a job

    0) Quit
""").strip("\n")

def main():
    os.makedirs("/home/keith/PythonProjects/projects/Mixed_Nuts/logs", exist_ok=True)
    while True:
        print("\n" + MENU)
        choice = input("Choose: ").strip()
        if choice == "0":
            print("Bye."); return

        if choice in {"1","2","3","4","5","6"}:
            if choice == "1": svc_status(); pause()
            elif choice == "2": svc_start(); pause()
            elif choice == "3": svc_stop(); pause()
            elif choice == "4": svc_restart(); pause()
            elif choice == "5": svc_logs(200, follow=False); pause()
            elif choice == "6": svc_logs(follow=True)
            continue

        conn = connect_db()
        if not conn:
            pause(); continue
        ensure_replies_table(conn)
        try:
            if choice == "7":
                list_jobs(conn); pause()
            elif choice == "8":
                show_recent_runs(conn, 20); pause()
            elif choice == "9":
                jid = int(input("Job ID: "))
                job_details(conn, jid); pause()
            elif choice == "10":
                jid = int(input("Job ID to run now: "))
                kick_job_now(conn, jid); pause()
            elif choice == "11":
                jid = int(input("Job ID to ENABLE: "))
                enable_job(conn, jid, True); pause()
            elif choice == "12":
                jid = int(input("Job ID to DISABLE: "))
                enable_job(conn, jid, False); pause()
            elif choice == "13":
                jid = int(input("Job ID to DELETE: "))
                delete_job(conn, jid); pause()
            elif choice == "14":
                jid = int(input("Job ID to view logs: "))
                n  = input(f"How many lines (default {DEFAULT_TAIL_LINES})? ").strip() or str(DEFAULT_TAIL_LINES)
                show_job_logs(conn, jid, int(n)); pause()
            elif choice == "15":
                add_echo_test(conn); pause()
            elif choice == "16":
                create_job_interactive(conn); pause()
            elif choice == "17":
                view_sms_replies(conn); pause()
            elif choice == "18":
                edit_job_interactive(conn); pause()
            elif choice == "19":
                copy_job_interactive(conn); pause()
            else:
                print("Invalid choice.")
        finally:
            try: conn.close()
            except Exception: pass

if __name__ == "__main__":
    main()
