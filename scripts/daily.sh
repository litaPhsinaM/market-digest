#!/bin/zsh
# Daily AI run (once a day, ~1 hour): new episodes → summaries → brief, top stories, quiz, audio, forecasts → publish.
#   ~/market-digest/scripts/daily.sh            run it now (shows progress)
# Starts Ollama, keeps the Mac awake while working, publishes, then quits Ollama. Log: logs/daily-YYYY-MM-DD.log
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH" DIGEST_BACKEND=ollama
mkdir -p logs
LOG="logs/daily-$(date +%F).log"

run() {
  echo "=== $(date) daily run ==="
  open -ga Ollama 2>/dev/null
  for i in {1..30}; do curl -s localhost:11434/api/version >/dev/null && break; sleep 1; done   # wait for the AI to start
  git pull --rebase --autostash --quiet origin main || true      # pick up the cloud's price snapshots first
  .venv/bin/python -u run.py --limit 2                             # new episodes, brief, top stories, prices, quiz, audio
  .venv/bin/python -u run.py --claims                              # Scorecard: log new forecasts, score due ones
  git add data && git commit -qm "Daily digest $(date +%F)" && git pull --rebase --autostash -q origin main && git push -q origin main \
    && echo "Published: https://litaphsinam.github.io/market-digest/"
  osascript -e 'quit app "Ollama"' 2>/dev/null                     # free the memory again
  echo "=== done $(date) ==="
}

# caffeinate keeps the Mac from sleeping until the run finishes (the lid must stay open).
caffeinate -i zsh -c "$(typeset -f run); run" 2>&1 | tee -a "$LOG" | grep --line-buffered -E '^===|: [0-9]+ new|✓|✗|Writing|Picking|Published|^!'
