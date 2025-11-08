#!/usr/bin/env bash
# launch_menu_v3.sh — launches the Mixed Nuts Script Menu (v3)

# Move to project folder (so relative paths work)
cd /home/keith/PythonProjects/projects/Mixed_Nuts || exit 1

# Optional: log launch event
echo "$(date '+%Y-%m-%d %H:%M:%S')  Launching menu_launcher_v3.py" >> menu_status.txt

# Run the Python launcher
python3 /home/keith/PythonProjects/projects/Mixed_Nuts/menu_launcher_v3.py

