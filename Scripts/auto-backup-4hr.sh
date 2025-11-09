#!/bin/bash
# ============================================================
# AUTO BACKUP SCRIPT — runs every 4 hours via cron
# ============================================================

LOGFILE="$HOME/folders-sync.log"
EXTREME_MOUNT="/media/keith/ExtremeSSD"
GDRIVE_REMOTE="gdrive:RcloneSyncMintFolder/2WaySyncMintGDocs"
LOCAL_SYNC="$EXTREME_MOUNT/2WaySyncMintGDocs"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOGFILE"
}

log "============================================="
log "🔁 4-HOUR BACKUP STARTED"
log "============================================="

# --- Verify mount exists ---
if [ ! -d "$EXTREME_MOUNT" ]; then
    log "❌ ERROR: External SSD not mounted at '$EXTREME_MOUNT'. Aborting."
    exit 1
fi

# --- Step 1: Local home folder sync ---
log "📂 Syncing home folder to external SSD..."
rsync -a --delete --exclude='.cache/' --exclude='Downloads/' --exclude='snap/' "$HOME/" "$EXTREME_MOUNT/home-backup/" \
    >> "$LOGFILE" 2>&1
if [ $? -eq 0 ]; then
    log "✅ Home folder sync completed successfully."
else
    log "⚠️ Warning: Errors occurred during home folder sync."
fi

# --- Step 2: rclone bisync (Google Drive) ---
log "☁️ Starting rclone bisync between Extreme SSD and Google Drive..."
rclone bisync "$LOCAL_SYNC" "$GDRIVE_REMOTE" \
    --compare size,modtime \
    --create-empty-src-dirs \
    --drive-skip-gdocs \
    --check-access \
    --progress >> "$LOGFILE" 2>&1

RC=$?

# --- Step 3: Auto-resync on cache error ---
if grep -q "Bisync critical error: cannot find prior Path1 or Path2 listings" "$LOGFILE"; then
    log "⚠️ Detected missing cache listings — retrying with --resync ..."
    rclone bisync "$LOCAL_SYNC" "$GDRIVE_REMOTE" \
        --resync \
        --compare size,modtime \
        --create-empty-src-dirs \
        --drive-skip-gdocs \
        --check-access \
        --progress >> "$LOGFILE" 2>&1
    RC=$?
fi

# --- Step 4: Finish and log result ---
if [ $RC -eq 0 ]; then
    log "✅ rclone bisync completed successfully."
else
    log "⚠️ rclone bisync reported warnings or errors. Check log for details."
fi

log "🏁 Backup cycle completed at $(date '+%Y-%m-%d %H:%M:%S')"
log "---------------------------------------------"

