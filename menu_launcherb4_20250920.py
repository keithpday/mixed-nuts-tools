#!/usr/bin/env python3
import os
import sqlite3
import subprocess
import sys
import shlex
from pathlib import Path

BASE_PATH = Path("/home/keith/PythonProjects/projects/Mixed_Nuts")
DB_PATH = BASE_PATH / "script_menu.db"

SUPPORTED_TYPES = {"python", "bash"}  # keep explicit; extend if you add more

# ---------------- DB helpers ----------------
def _table_columns(conn, table_name: str) -> set[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}  # row[1] = column name

def load_menu_items():
    """
    Returns a list of dicts. Handles both old schema and new (args/base_path) seamlessly.
    Required base columns: id, option_number, label, command, type, working_dir, program_path
    Optional columns: args, base_path
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cols = _table_columns(conn, "menu_items")
    # Build a SELECT that only includes available columns
    base_cols = ["id", "option_number", "label", "command", "type", "working_dir", "program_path"]
    opt_cols  = [c for c in ("args", "base_path") if c in cols]
    select_cols = base_cols + opt_cols

    cur.execute(f"""
        SELECT {", ".join(select_cols)}
        FROM menu_items
        ORDER BY option_number
    """)
    rows = cur.fetchall()
    conn.close()

    items = []
    for row in rows:
        rec = dict(zip(select_cols, row))
        # Normalize missing optional fields
        rec.setdefault("args", "")
        rec.setdefault("base_path", "")
        items.append(rec)
    return items

# ---------------- Path + argv resolution ----------------
def _resolve_base_dir(item: dict) -> Path:
    """
    Priority: working_dir (cwd) if set; else base_path (for resolving program_path); else BASE_PATH.
    We still use working_dir as cwd, and base_path to resolve program_path when it's relative.
    """
    wd = (item.get("working_dir") or "").strip()
    bp = (item.get("base_path") or "").strip()
    if wd:
        return Path(wd)
    if bp:
        return Path(bp)
    return BASE_PATH

def _resolve_program_path(item: dict, base_dir: Path) -> Path:
    """
    Determine the script file to execute.
    Primary source: program_path (recommended).
    Fallback: if program_path empty, derive from the first token in 'command'.
    """
    prog = (item.get("program_path") or "").strip()
    if prog:
        p = Path(prog)
        return p if p.is_absolute() else (base_dir / p)

    # Fallback: parse command, treat the first token as the script path
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
    """
    Build argv list of arguments (excluding interpreter and script).
    Sources (in order):
      1) args column (preferred)
      2) remaining tokens from command (excluding the program token) — for backward compatibility
    Both are split with shlex to handle quotes.
    """
    out = []
    args_text = (item.get("args") or "").strip()
    if args_text:
        out.extend(shlex.split(args_text))

    cmd = (item.get("command") or "").strip()
    if cmd:
        toks = shlex.split(cmd)
        if len(toks) > 1:
            out.extend(toks[1:])  # everything after the program token
    return out

def _build_command(item: dict) -> tuple[list[str], Path]:
    """
    Returns (argv, cwd_path).
    - For type 'python': [sys.executable, <script>, *args]
    - For type 'bash':   ['bash', <script>, *args]
    """
    type_ = (item.get("type") or "").strip().lower()
    if type_ not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported type: {type_!r}. Supported: {', '.join(sorted(SUPPORTED_TYPES))}")

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
        # should not happen due to SUPPORTED_TYPES gate
        argv = [str(script_path)] + args

    return argv, base_dir

# ---------------- Runner ----------------
def run_menu_item(item: dict):
    label = item.get("label") or "(unnamed)"
    type_ = item.get("type") or ""
    print(f"\n🟢 Running: {label} ({type_})\n")

    try:
        argv, cwd = _build_command(item)
    except Exception as e:
        print(f"❌ Could not build command: {e}")
        return

    # Helpful info for troubleshooting
    # print(f"cwd={cwd}\nargv={argv}\n")  # uncomment if needed

    try:
        subprocess.run(argv, cwd=str(cwd))
    except FileNotFoundError as e:
        print(f"❌ File not found: {e.filename}")
        # Extra hint if script path is wrong due to base path:
        if not Path(argv[1] if len(argv) > 1 else "").exists():
            print("   Tip: check program_path and base_path/working_dir columns.")
    except Exception as e:
        print(f"❌ Failed to run: {e}")

# ---------------- UI ----------------
def main():
    while True:
        items = load_menu_items()
        print("\n=== 🎵 Mixed Nuts Script Menu (menu_launcher.py) ===")
        for item in items:
            print(f"{item['option_number']}. {item['label']}")
        print("0. Exit")

        choice = input("\nSelect an option number: ").strip()
        if choice == "0":
            print("Goodbye!")
            break

        # find selected item by option_number
        selected = None
        for i in items:
            if str(i["option_number"]) == choice:
                selected = i
                break

        if not selected:
            print("❌ Invalid choice. Please try again.")
            continue

        run_menu_item(selected)

if __name__ == "__main__":
    main()
