#!/bin/zsh
# Hourly during US market hours: refresh prices (fills paper trades, scores predictions) and republish.
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# Only on weekdays between 9:30 and 16:30 New York time.
NY_DAY=$(TZ=America/New_York date +%u); NY_HM=$(TZ=America/New_York date +%H%M)
[[ $NY_DAY -le 5 && $NY_HM -ge 0930 && $NY_HM -le 1630 ]] || exit 0
pgrep -f "run.py --limit" >/dev/null && exit 0   # the morning run is busy; skip this hour
mkdir -p logs
LOG="logs/prices-$(date +%F).log"
{
  echo "--- $(date) prices"
  .venv/bin/python -u run.py --market-only
  git add data/market && git commit -qm "Prices $(TZ=America/New_York date '+%F %H:%M') ET" && git pull --rebase -q origin main && git push -q origin main
} >> "$LOG" 2>&1
