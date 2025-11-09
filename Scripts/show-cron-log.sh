#!/bin/bash
echo "═══════════════════════════════════════════════"
echo "🕓 RECENT CRON LOG ENTRIES"
echo "═══════════════════════════════════════════════"
sudo env MENU_LAUNCHER_MODE=$MENU_LAUNCHER_MODE grep CRON /var/log/syslog | tail -n 30
echo
echo "═══════════════════════════════════════════════"
echo "📄 LAST 20 LINES OF ~/folders-sync.log"
echo "═══════════════════════════════════════════════"
tail -n 20 ~/folders-sync.log
echo
# Only pause if not launched from menu_launcher
if [ -z "$MENU_LAUNCHER_MODE" ]; then
  read -p "Press ENTER to close..."
fi


