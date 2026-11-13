# Stocksplain (repo: market-digest): notes for AI assistants

A free app that teaches beginners investing: it turns 15 finance podcasts and 27 newsrooms into a 5-minute daily
lesson, with quizzes, lessons, paper trading and a pundit scorecard. Live at https://stocksplain.app/ (GitHub Pages custom domain; the old github.io address redirects)
(web, Android APK, iPhone app via Capacitor). Owner: Manish (GitHub `litaPhsinaM`).

## Rules that matter most

- **Education, never advice.** No buy/sell recommendations, price targets or "you should". Opinions are labelled as
  the speaker's. Paper trading is play money and is always described that way.
- **Every number, ticker and quote must match its source.** `digest/checks.py` (summaries, hot topics) and
  `digest/claims.py` (forecast quotes) enforce this; don't weaken them to make a run pass.
- **Usernames are public** on leaderboards: never derive them from emails.
- **Pull before pushing:** a bot commits price snapshots every 15 minutes in market hours, so always
  `git pull --rebase --autostash` (or `--no-rebase` for merges) before `git push`.
- **Database migrations are applied by the owner.** Write `supabase/migrations/NNN_name.sql`, test it inside a
  rolled-back transaction, then ask Manish to run `.venv/bin/python migrate.py`. Don't change production data or
  cron jobs directly.
- **Secrets live in `.env` (git-ignored) and GitHub/Supabase secrets.** Never print them, commit them, or ask for them
  in chat; ask the owner to paste them into `.env`.
- Test UI changes at phone width (390px) and desktop (1440px), light and dark, before publishing.

## How it runs

```
Supabase pg_cron (the clock)
 ├─ 5:30 am ET weekdays → .github/workflows/daily.yml: podcast RSS → Gemini transcript + summary → checks →
 │                         brief, hot topics, quiz, Kokoro audio, forecasts → commit data/ → publish
 ├─ every 15 min, market hours → prices.yml: Yahoo → Supabase prices (fills paper trades, settles calls) → publish
 └─ after the close → public.after_close(): range-game scoring + portfolio snapshots (Sharpe, drawdown)
GitHub Pages: static site built by digest/build.py from templates/ + data/
```

- `run.py`: the pipeline. `--build-only` (no AI), `--market-only`, `--hot-only`, `--extras-only`, `--claims`, `--redo`.
- `digest/`: sources (RSS), transcribe (local Whisper), summarize (Gemini or Ollama, with a model fallback chain and
  hard timeouts), checks, claims, market (yfinance), hours (NYSE calendar: holidays, early closes), supa, voice
  (Kokoro), build.
- `templates/`: Jinja pages + plain JS modules (`app.js`, `features.js`, `account.js`, `social.js`, `quant.js`,
  `learn.js`, `admin.js`) sharing `window.MD`.
- `supabase/migrations/`: schema, row-level security, all game logic (orders, predictions, rewards, range game).
- `mobile/`: Capacitor shell that loads the live site (Android + iOS; iOS needs `SceneDelegate.swift` for iOS 27).
- `scripts/daily.sh`: offline Mac fallback (Whisper + Ollama qwen3:14b).
- `docs/ideas-from-daily-stock-analysis.md`: the prioritized feature backlog.

## Gotchas learned the hard way

- GitHub's own cron never fired for this repo; the database timer (`015`, `016` migrations) starts jobs instead.
- Gemini free tier: some models are overloaded (503) or have tiny daily quotas; keep the fallback chain and timeouts.
- The Play page reads the newest prices (the API returns at most 1,000 rows per request).
- `data/audio/*.mp3` must be committed, or the live site has no audio.
- Supabase direct DB host is IPv6-only: use the session pooler URL in `.env` (`SUPABASE_DB_URL`).
