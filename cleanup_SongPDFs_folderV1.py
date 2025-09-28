import os
import re
from datetime import datetime

# === CONFIG ===
FOLDER = "/home/keith/Desktop/data (MixedNutsLib)/SongPDFs"
DRY_RUN = False  # Change to False to actually delete files

# Regex: match "SongName(KVF)" and optional revision date (various formats)
pattern = re.compile(r"^(.*?\(K..?\))(?:[.\-]?(\d{4}[\d\.]*))?\.pdf$", re.IGNORECASE)


def normalize_date(date_str):
    """Convert date string into YYYYMMDD for comparison, or return None."""
    if not date_str:
        return None
    digits = re.sub(r"\D", "", date_str)  # keep only numbers
    try:
        if len(digits) == 8:
            return datetime.strptime(digits, "%Y%m%d").strftime("%Y%m%d")
        elif len(digits) == 6:  # e.g. YYYYMM
            return datetime.strptime(digits, "%Y%m").strftime("%Y%m%d")
        elif len(digits) == 4:  # e.g. YYYY
            return datetime.strptime(digits, "%Y").strftime("%Y%m%d")
    except ValueError:
        return None
    return digits


def parse_filename(fname):
    match = pattern.match(fname)
    if not match:
        print(f"⚠️ Regex did not match: {fname}")
        return None, None
    base_name = match.group(1)
    date_str = normalize_date(match.group(2))
    print(f"✅ Matched: {fname} → base='{base_name}', date='{date_str}'")
    return base_name, date_str


def main():
    files = [f for f in os.listdir(FOLDER) if f.lower().endswith(".pdf")]
    groups = {}

    for fname in files:
        base_name, date_str = parse_filename(fname)
        if not base_name:
            continue
        groups.setdefault(base_name, []).append((fname, date_str))

    for base, items in groups.items():
        if len(items) <= 1:
            continue

        # Sort by date, None = oldest
        items_sorted = sorted(items, key=lambda x: (x[1] is None, x[1] or ""))
        keep = items_sorted[-1]  # newest
        to_delete = [f for f in items_sorted if f != keep]

        print(f"\n📂 Group: {base}")
        print(f"   Keeping: {keep[0]}")
        for f, d in to_delete:
            if DRY_RUN:
                print(f"   Would delete: {f}")
            else:
                path = os.path.join(FOLDER, f)
                os.remove(path)
                print(f"   Deleted: {f}")


if __name__ == "__main__":
    main()
