#!/bin/bash
cd /home/keith/PythonProjects/projects/Mixed_Nuts || exit

echo "Checking git status..."
git status

echo
read -p "Add ALL changed files? (y/n): " answer
if [[ "$answer" =~ ^[Yy]$ ]]; then
    git add -A
    echo "All changed files added to staging area."
    git status
else
    echo "No files added."
fi


