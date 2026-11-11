#!/bin/zsh
# Morning run: new episodes → summaries → brief, hot topics, quiz, audio, forecasts, prices → publish.
# Scheduled by launchd (see scripts/install-schedule.sh).
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH" DIGEST_BACKEND=ollama
mkdir -p logs
LOG="logs/daily-$(date +%F).log"
{
  echo "=== $(date) daily run ==="
  open -ga Ollama 2>/dev/null; sleep 5   # make sure the local AI is running
  git pull --rebase --quiet origin main || true
  .venv/bin/python -u run.py --limit 2
  .venv/bin/python -u run.py --claims    # log forecasts from new episodes, score due ones
  git add data && git commit -qm "Daily digest $(date +%F)" && git push -q origin main
  echo "=== done $(date) ==="
} >> "$LOG" 2>&1
