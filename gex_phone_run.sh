#!/bin/bash
# Cron wrapper for gex_phone.py: one run at a time, pushes to GitHub (PUSH=1), logs to logs/gex_phone.log
export PATH="/Library/Frameworks/Python.framework/Versions/3.14/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="/Users/gl"
cd /Users/gl/gex-dashboard || exit 1
LOCK=/tmp/gex_phone.lock
if ! mkdir "$LOCK" 2>/dev/null; then
  # stale lock (>20 min old) from a crashed run -> clear it, otherwise skip this tick
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +20 2>/dev/null)" ]; then rmdir "$LOCK"; mkdir "$LOCK" || exit 0; else echo "$(date) skipped: previous run still going" >> logs/gex_phone.log; exit 0; fi
fi
trap 'rmdir "$LOCK"' EXIT
echo "=== $(date) ===" >> logs/gex_phone.log
PUSH=${PUSH:-1} caffeinate -i phone-harness < gex_phone.py >> logs/gex_phone.log 2>&1
