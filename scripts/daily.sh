#!/bin/zsh
# Daily AI run (once a day, ~1 hour): new episodes → summaries → brief, top stories, quiz, audio, forecasts → publish.
#   ~/market-digest/scripts/daily.sh            run it now (shows progress)
# Starts Ollama, keeps the Mac awake while working, publishes, then quits Ollama. Log: logs/daily-YYYY-MM-DD.log
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH" DIGEST_BACKEND=ollama
mkdir -p logs
LOG="logs/daily-$(date +%F).log"

# Commit and push data/. The cloud commits today's price snapshot every 15 minutes, so that one file can conflict:
# keep this run's copy (it also covers the companies in today's stories); anything else conflicting stops the push.
publish() {
  git add data && { git diff --cached --quiet || git commit -qm "Daily digest $(date +%F)"; }
  for i in 1 2 3; do
    if ! git pull --rebase --autostash -q origin main; then
      local c=$(git diff --name-only --diff-filter=U)
      if [ -n "$c" ] && ! print -r -- "$c" | grep -qv '^data/market/'; then
        git checkout --theirs -- ${(f)c} && git add -- ${(f)c} && GIT_EDITOR=true git rebase --continue >/dev/null
      fi
      git rebase --abort 2>/dev/null   # no-op if the rebase finished
    fi
    [ -n "$(git rev-list origin/main..HEAD 2>/dev/null)" ] || return 0   # nothing left to push
    git push -q origin main && return 0
    sleep 10
  done
  echo "! couldn't push to GitHub: today's digest is saved locally only"; return 1
}

run() {
  echo "=== $(date) daily run ==="
  open -ga Ollama 2>/dev/null
  for i in {1..30}; do curl -s localhost:11434/api/version >/dev/null && break; sleep 1; done   # wait for the AI to start
  curl -s localhost:11434/api/version >/dev/null || echo "! Ollama didn't start: no new summaries today (prices still update)"
  # pick up the cloud's price snapshots first; never stay stuck mid-rebase if that fails
  git pull --rebase --autostash --quiet origin main || { git rebase --abort 2>/dev/null; echo "! couldn't update from GitHub first"; }
  .venv/bin/python -u run.py --limit 2                             # new episodes, brief, top stories, prices, quiz, audio
  .venv/bin/python -u run.py --claims                              # Scorecard: log new forecasts, score due ones
  publish && echo "Published: https://litaphsinam.github.io/market-digest/"
  osascript -e 'quit app "Ollama"' 2>/dev/null                     # free the memory again
  echo "=== done $(date) ==="
}

# caffeinate keeps the Mac from sleeping until the run finishes (the lid must stay open).
caffeinate -i zsh -c "$(typeset -f publish run); run" 2>&1 | tee -a "$LOG" | grep --line-buffered -E '^===|: [0-9]+ new|✓|✗|Writing|Picking|Published|^!'
