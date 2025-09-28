#!/usr/bin/env python3
import os, shlex, json, sqlite3, subprocess, time, traceback, sys
from datetime import datetime, timezone, timedelta
from dateutil import tz
from croniter import croniter

DB_PATH = "/home/keith/PythonProjects/projects/Mixed_Nuts/MyScheduler/myscheduler.db"
POLL_SECONDS = 20
MAX_CONCURRENCY = 4

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

def utcnow(): return datetime.now(timezone.utc)
def parse_args(s):
    s = (s or "").strip()
    if s.startswith("["): return json.loads(s)
    import shlex as _sh; return _sh.split(s)

def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS jobs (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      program_path TEXT NOT NULL,
      args TEXT DEFAULT '',
      working_dir TEXT DEFAULT NULL,
      venv_path TEXT DEFAULT NULL,
      env_json TEXT DEFAULT NULL,
      schedule_type TEXT NOT NULL CHECK (schedule_type IN ('cron','interval','once')),
      cron_expr TEXT DEFAULT NULL,
      interval_seconds INTEGER DEFAULT NULL,
      once_at_utc TEXT DEFAULT NULL,
      timezone TEXT DEFAULT 'America/Denver',
      enabled INTEGER NOT NULL DEFAULT 1,
      no_overlap INTEGER NOT NULL DEFAULT 1,
      timeout_seconds INTEGER DEFAULT 0,
      retries INTEGER DEFAULT 0,
      retry_backoff_sec INTEGER DEFAULT 60,
      max_runs INTEGER DEFAULT NULL,
      run_count INTEGER NOT NULL DEFAULT 0,
      next_run_utc TEXT DEFAULT NULL,
      last_run_utc TEXT DEFAULT NULL,
      running INTEGER NOT NULL DEFAULT 0,
      last_exit_code INTEGER DEFAULT NULL,
      stdout_path TEXT DEFAULT NULL,
      stderr_path TEXT DEFAULT NULL,
      log_path TEXT DEFAULT NULL,
      created_at_utc TEXT NOT NULL DEFAULT (datetime('now')),
      updated_at_utc TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON jobs(next_run_utc);
    CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled);
    CREATE TABLE IF NOT EXISTS runs (
      id INTEGER PRIMARY KEY,
      job_id INTEGER NOT NULL,
      started_utc TEXT NOT NULL,
      finished_utc TEXT,
      status TEXT NOT NULL,
      exit_code INTEGER,
      pid INTEGER,
      message TEXT,
      stdout_path TEXT,
      stderr_path TEXT,
      FOREIGN KEY(job_id) REFERENCES jobs(id)
    );""")
    conn.commit()

def compute_next_run(job, now_utc):
    tzname = job.get("timezone") or "America/Denver"
    local_tz = tz.gettz(tzname)
    if job["schedule_type"] == "cron":
        expr = job.get("cron_expr")
        if not expr: return None
        base_local = now_utc.astimezone(local_tz).replace(microsecond=0)
        nxt_local = datetime.fromtimestamp(croniter(expr, base_local).get_next(float), tz=local_tz)
        return nxt_local.astimezone(timezone.utc)
    if job["schedule_type"] == "interval":
        sec = int(job.get("interval_seconds") or 0)
        if sec <= 0: return None
        last = job.get("last_run_utc")
        base = datetime.fromisoformat(last).replace(tzinfo=timezone.utc) if last else now_utc
        return base + timedelta(seconds=sec)
    if job["schedule_type"] == "once":
        ts = job.get("once_at_utc")
        if not ts: return None
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        return dt if dt > now_utc else now_utc

def refresh_missing_next_runs(conn):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE enabled=1 AND next_run_utc IS NULL")
    rows = cur.fetchall()
    now = utcnow()
    for r in rows:
        job = dict(r)
        nxt = compute_next_run(job, now)
        cur.execute("UPDATE jobs SET next_run_utc=?, updated_at_utc=datetime('now') WHERE id=?",
                    (nxt.isoformat() if nxt else None, job["id"]))
    conn.commit()

def claim_due_jobs(conn):
    cur = conn.cursor()
    cur.execute("""
      SELECT id FROM jobs
      WHERE enabled=1 AND next_run_utc IS NOT NULL AND next_run_utc <= ?
        AND (no_overlap=0 OR running=0)
      ORDER BY next_run_utc ASC
      LIMIT ?""", (utcnow().isoformat(), MAX_CONCURRENCY*2))
    ids = [r[0] for r in cur.fetchall()]
    claimed = []
    for jid in ids:
        cur.execute("UPDATE jobs SET running=1, updated_at_utc=datetime('now') WHERE id=? AND (running=0 OR no_overlap=0)", (jid,))
        if cur.rowcount: claimed.append(jid)
    conn.commit()
    return claimed

def log_run(conn, job_id, status, **kw):
    conn.execute("""INSERT INTO runs (job_id, started_utc, finished_utc, status, exit_code, pid, message, stdout_path, stderr_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                 (job_id, kw.get("started_utc") or utcnow().isoformat(), kw.get("finished_utc"),
                  status, kw.get("exit_code"), kw.get("pid"), kw.get("message"),
                  kw.get("stdout_path"), kw.get("stderr_path")))
    conn.commit()

def run_job(conn, job):
    started = utcnow()
    prog = job["program_path"]
    parsed = parse_args(job.get("args"))
    py = os.path.join(job["venv_path"], "bin", "python") if job.get("venv_path") else "/usr/bin/python3"
    args = [py, prog] + parsed if prog.endswith(".py") else [prog] + parsed
    env = os.environ.copy()
    if job.get("env_json"):
        try: env.update(json.loads(job["env_json"]))
        except Exception: pass
    try:
        proc = subprocess.Popen(args, cwd=job.get("working_dir") or None, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            out, err = proc.communicate(timeout=(int(job.get("timeout_seconds") or 0) or None))
            status = "ok" if proc.returncode == 0 else "error"
            if job.get("stdout_path"):
                os.makedirs(os.path.dirname(job["stdout_path"]), exist_ok=True)
                open(job["stdout_path"], "a", encoding="utf-8").write(out or "")
            if job.get("stderr_path"):
                os.makedirs(os.path.dirname(job["stderr_path"]), exist_ok=True)
                open(job["stderr_path"], "a", encoding="utf-8").write(err or "")
            log_run(conn, job["id"], status, started_utc=started.isoformat(),
                    finished_utc=utcnow().isoformat(), exit_code=proc.returncode,
                    stdout_path=job.get("stdout_path"), stderr_path=job.get("stderr_path"))
            return status, proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill(); out, err = proc.communicate()
            log_run(conn, job["id"], "timeout", started_utc=started.isoformat(),
                    finished_utc=utcnow().isoformat(), message="Process timed out",
                    stdout_path=job.get("stdout_path"), stderr_path=job.get("stderr_path"))
            return "timeout", None
    except Exception as e:
        print("JOB ERROR:", e, flush=True); traceback.print_exc()
        log_run(conn, job["id"], "error", started_utc=started.isoformat(),
                finished_utc=utcnow().isoformat(), message=str(e))
        return "error", None

def read_job(conn, job_id):
    conn.row_factory = sqlite3.Row
    cur = conn.cursor(); cur.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    r = cur.fetchone(); return dict(r) if r else None

def compute_and_update_next(conn, job, status, exit_code):
    now = utcnow(); cur = conn.cursor()
    run_count = int(job.get("run_count") or 0) + 1
    if job["schedule_type"] == "once":
        nxt_iso = None
    else:
        nxt = compute_next_run(job, now); nxt_iso = nxt.isoformat() if nxt else None
    cur.execute("""UPDATE jobs SET next_run_utc=?, last_run_utc=?, run_count=?, last_exit_code=?, running=0, updated_at_utc=datetime('now') WHERE id=?""",
                (nxt_iso, now.isoformat(), run_count, exit_code, job["id"]))
    conn.commit()

def main():
    print(f"[{utcnow().isoformat()}] scheduler starting; DB={DB_PATH}", flush=True)
    try:
        conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL;"); conn.execute("PRAGMA busy_timeout=5000;")
        ensure_schema(conn)
    except Exception as e:
        print("FATAL during DB init:", e, flush=True); traceback.print_exc(); return
    while True:
        try:
            refresh_missing_next_runs(conn)
            claimed = claim_due_jobs(conn)
            print(f"[{utcnow().isoformat()}] tick; claimed={claimed}", flush=True)
            for jid in claimed[:MAX_CONCURRENCY]:
                job = read_job(conn, jid)
                if not job: continue
                status, code = run_job(conn, job)
                compute_and_update_next(conn, job, status, code)
            time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("Exiting on Ctrl-C", flush=True); break
        except Exception as e:
            print("LOOP ERROR:", e, flush=True); traceback.print_exc(); time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
