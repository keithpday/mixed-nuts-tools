#!/usr/bin/env python3
import os
import re
import shutil
import csv

# Source and destination folders
src_folder = "/home/keith/Desktop/data (MixedNutsLib)/UnMarked"
dst_folder = "/home/keith/Desktop/data (MixedNutsLib)/SongPDFs"

# Regex to match valid "prefixes" (set IDs etc.) ending in a dash
# Example matches: "AA10-", "Christmas2-05-", "JBOX04-"
prefix_pattern = re.compile(r"^([A-Za-z]{1,10}[A-Za-z0-9_]*\d*-\d{0,2}-?|[A-Za-z0-9_]+-)+")

# CSV report file
report_file = os.path.join(dst_folder, "rename_report.csv")

def clean_filename(filename):
    base, ext = os.path.splitext(filename)
    # Only process PDFs
    if ext.lower() != ".pdf":
        return filename, "SKIPPED (not PDF)"

    # Try to strip recognized prefixes
    new_base = prefix_pattern.sub("", base)

    # If stripping nuked too much (too short or empty), flag for review
    if len(new_base) < 5 or new_base == base:
        status = "OK (no change)"
    elif len(new_base) < len(base) * 0.5:  # dropped more than half the name
        status = "⚠️ REVIEW"
    else:
        status = "OK"

    return new_base + ext, status

def main():
    if not os.path.exists(dst_folder):
        os.makedirs(dst_folder)

    with open(report_file, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Original", "Renamed", "Status"])

        for fname in sorted(os.listdir(src_folder)):
            src_path = os.path.join(src_folder, fname)
            if not os.path.isfile(src_path):
                continue

            new_name, status = clean_filename(fname)
            dst_path = os.path.join(dst_folder, new_name)

            try:
                shutil.copy2(src_path, dst_path)
                print(f"Copying: {fname} -> {new_name} [{status}]")
                writer.writerow([fname, new_name, status])
            except Exception as e:
                print(f"❌ Failed to copy {fname}: {e}")
                writer.writerow([fname, fname, f"ERROR: {e}"])

    print(f"\n✅ Done. Report saved to {report_file}")

if __name__ == "__main__":
    main()
