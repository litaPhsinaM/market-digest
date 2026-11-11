#!/bin/zsh
# Hourly during US market hours: refresh prices (fills paper trades, scores predictions) and republish.
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
# Only on trading days, from the open to 15 minutes after the close (holidays and early closes: digest/hours.py).
.venv/bin/python digest/hours.py >/dev/null || exit 0
pgrep -f "run.py --limit" >/dev/null && exit 0   # the morning run is busy; skip this hour
mkdir -p logs
LOG="logs/prices-$(date +%F).log"
{
  echo "--- $(date) prices"
  .venv/bin/python -u run.py --market-only
  git add data/market && git commit -qm "Prices $(TZ=America/New_York date '+%F %H:%M') ET"
  if ! git pull --rebase --autostash -q origin main; then
    # The cloud job saved the same snapshot file: keep this (newer) copy. Anything else: give up, never stay mid-rebase.
    c=$(git diff --name-only --diff-filter=U)
    if [ -n "$c" ] && ! print -r -- "$c" | grep -qv '^data/market/'; then
      git checkout --theirs -- ${(f)c} && git add -- ${(f)c} && GIT_EDITOR=true git rebase --continue
    fi
    git rebase --abort 2>/dev/null
  fi
  git push -q origin main
} >> "$LOG" 2>&1
