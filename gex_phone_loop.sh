#!/bin/bash
# Runs gex_phone_run.sh every 10 minutes, Mon-Fri 06:00-12:50 local (PT). Start inside the Claude app's Terminal
# (that process already has Screen Recording / Accessibility access; cron does not). Ctrl-C to stop.
cd /Users/gl/gex-dashboard || exit 1
echo "gex phone loop started $(date)"
while true; do
  H=$(date +%H); H=$((10#$H)); D=$(date +%u)
  M=$((10#$(date +%M)))
  # Mon-Fri, 06:00 through 12:50 PT (last run 12:50, before the 13:00 close)
  if [ "$D" -le 5 ] && [ "$H" -ge 6 ] && { [ "$H" -le 11 ] || { [ "$H" -eq 12 ] && [ "$M" -le 50 ]; }; }; then
    ./gex_phone_run.sh
  fi
  # sleep to the next 10-minute mark
  M=$((10#$(date +%M))); S=$((10#$(date +%S)))
  sleep $(( (10 - M % 10) * 60 - S ))
done
