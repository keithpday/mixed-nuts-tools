#!/bin/bash
# ====================================================
# Show current user's cron jobs and cron service status
# ====================================================

echo "═══════════════════════════════════════════════"
echo "🕓 CURRENT USER CRON JOBS"
echo "═══════════════════════════════════════════════"
crontab -l 2>/dev/null || echo "No crontab entries found for user $(whoami)."

echo ""
echo "═══════════════════════════════════════════════"
echo "⚙️  CRON SERVICE STATUS (brief)"
echo "═══════════════════════════════════════════════"
systemctl is-active cron >/dev/null && echo "✅ cron service is running." || echo "❌ cron service is NOT running."

echo ""
# Only pause if not launched from menu_launcher
if [ -z "$MENU_LAUNCHER_MODE" ]; then
  read -p "Press ENTER to close..."
fi

