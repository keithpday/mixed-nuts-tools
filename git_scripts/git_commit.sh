#!/bin/bash
cd /home/keith/PythonProjects/projects/Mixed_Nuts || exit

echo -n "Enter commit message: "
read msg

if [ -z "$msg" ]; then
  echo "⚠️ Commit aborted (empty message)."
  exit 1
fi

# Stage everything (respects .gitignore)
git add .

# Commit
git commit -m "$msg"

# Optional: push immediately
# Comment this out if you prefer separate push step
git push

