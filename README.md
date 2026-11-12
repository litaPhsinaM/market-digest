# Stocksplain

**Learn the market in 5 minutes a day.** Every morning Stocksplain listens to 15 trusted finance podcasts and scans
12 newsrooms, then explains what matters in plain English: the key points, the numbers, the jargon and the lesson
behind the news. It's built for people who are new to investing.

- **Website:** https://stocksplain.app/
- **Android app:** [download the latest APK](https://github.com/litaPhsinaM/market-digest/releases/latest)
- **iPhone:** open the website in Safari → **Share → Add to Home Screen**

## What's inside

### 📰 Today
- **Story cards** for each new episode: tap for the full study sheet with key points, the numbers that matter, the
  lesson, opinions kept separate from facts, words to know, and a link to the original. Tap **✓** when you've read it.
- **Top stories**: the day's biggest stories, grouped from 100+ newsroom headlines, each with "why it matters".
  On phones they're a swipeable card stack.
- **Today in 60 seconds**: swipe through the day as full-screen cards.
- **Audio briefing**: a 3-minute spoken summary of the day.
- **Daily quiz**: three questions on today's stories.
- **Market strip** (S&P 500, Nasdaq, Dow, 10-year Treasury, Bitcoin) with an (i) explanation on each, plus a
  **market mood** gauge from fear to greed.
- **Companies in the news**: price, chart (1M/6M/1Y), P/E, market cap, dividend, next earnings date and headlines.
  ★ Star companies to build a watchlist; upcoming **earnings** are listed with yours on top.
- **Biggest movers**: today's top gainers, losers and most-traded stocks.

### 🎓 Learn
- **Start here**: 29 short lessons in 6 units, from "what is a stock?" to reading a company, avoiding scams, and how
  traders read charts (moving averages, MACD, RSI, chart and factor strategies, and why most strategies fail),
  each with a worked example, key terms, a "try it" task and a 3-question quiz.
- **Practice by level**: 90 original questions at 🟢 foundation, 🟡 intermediate (FINRA SIE exam topics) and
  🔴 advanced (CFA Level I topics) levels. Not affiliated with either.
- **Go deeper**: 80 free resources from SEC Investor.gov, TreasuryDirect, the Federal Reserve, FDIC, CFPB, MIT
  OpenCourseWare, Yale and more. Every link was checked when it was added.

### 🎮 Play (free account)
- **Paper trading**: start with $10,000 of play money and **earn more by learning**: correct quiz answers (+$100), finished lessons (+$500), right calls (+$100–$400) and 7-day streaks (+$1,000). Orders fill at the next price update, like a real order placed after hours. Rankings use your return on everything you have earned, so learning makes you richer but only good investing tops the board.
- **Predictions with confidence**: call a stock up or down for tomorrow and say how sure you are. Calls are scored for
  calibration (the Brier score), so judgement beats luck.
- **Daily range game** 🎯: "Where will the S&P 500 close?" Set a range you're 90% sure of. Scored with an interval
  score (tight and right wins; a miss costs 20× the distance), up to 100 points = $200, with your hit rate shown so
  you can see whether your "90% sure" really is.
- **Your stats** 📐: every trade is mirrored into the S&P 500 at the same moment, so you see your **alpha** (did you
  beat the market?), plus a Sharpe-style risk-adjusted score and max drawdown from daily snapshots. New ⚖️ Skill and
  🎯 Range leaderboards.
- **🤖 TrendBot**: a robot player that trades daily with the 100-point chart checklist from the open-source
  [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) (MIT), with every move and its reasons public.
- **Coach**: points out panic selling, putting everything in one stock or overtrading, with a link to the lesson.
- **Friends and leaderboards**: follow friends by username or invite link; rankings for streaks, quizzes,
  forecasting skill, portfolio return, risk-adjusted skill and the range game. Streaks are counted by the server.

### 🎙 Scorecard
Forecasts made on the shows ("X expects a rate hike in December") are logged in the speaker's exact words and scored
when their deadline passes. Over time it shows who is actually right about markets.

### Everywhere
🔥 streaks · ⌘K search across every story, term and company · light/dark mode · works offline once loaded ·
installable as an app · share any story as an image · a phone layout with a bottom tab bar and a swipeable market
strip · honest timing labels (market open, closed, weekend or holiday; prices running late) · light days get bigger
cards so the page never looks empty.

## Accounts, sync and privacy

- **No account needed** for reading, Learn or the quizzes. Progress is saved on your device.
- **Signing in** (an email link or 6-digit code, no password) syncs your streak, stories read, quiz answers, lessons,
  practice scores and watchlist between your phone and computer, and unlocks Play.
- **What we store** for signed-in users: your email, your progress, and your games (trades, predictions, follows).
  Leaderboards show only your username and game stats. Each person can only read their own data.
- **Usage counts**: the app records anonymous events (e.g. "opened a story", "finished a lesson") with a random device
  id, to see which features help people. No names, no tracking across other sites, no ads.

## Good to know

- Summaries are written by AI from public podcast episodes and newsroom headlines. They can contain mistakes, so
  check the original (linked on every story) before relying on a number.
- Market data is from Yahoo Finance and may be delayed. Games use real prices but no real money.
- **Nothing here is financial advice.**
- Not affiliated with any show, newsroom or company mentioned. We publish short summaries in our own words, never
  transcripts or full articles, and always link back. Creators who want a show removed can
  [open a request](https://github.com/litaPhsinaM/market-digest/issues/new?title=Removal%20request).

## Sources

15 podcasts (WSJ, Bloomberg, CNBC, NPR, Marketplace, Freakonomics, Odd Lots, Rational Reminder, Goldman Sachs and
more) and 12 newsroom feeds; the full list with the reason each was chosen is on the
[Sources page](https://stocksplain.app/sources.html) and in `sources.yaml`.

---

## For developers

### How it works

```
Supabase pg_cron (the clock)
 ├─ 5:30 am ET weekdays → GitHub Actions "Daily digest": podcast RSS → Gemini transcript + summary → checks →
 │                         brief, hot topics, quiz, Kokoro audio, forecasts → commit data/ → publish
 └─ every 15 min, market hours → GitHub Actions "Update prices": Yahoo Finance → Supabase (fills trades, scores
                                 calls) → publish
GitHub Pages: the static site (this repo)  ◄─►  Supabase: accounts, synced progress, games, usage events
```

The AI runs once a day in GitHub Actions on Gemini's free tier (falling back across Flash models), or on a Mac with
local models (Whisper + Qwen 14B via Ollama) as an offline backup. The site is static; the browser talks to Supabase
directly with the public key, and row-level security keeps each user's data private. Jobs are started by Supabase's
pg_cron (GitHub's own scheduler skips runs), and the NYSE holiday calendar lives in `digest/hours.py` and the database.
The Android app (`mobile/`) is a Capacitor shell that loads the live site, so content and features update without a
new APK.

### Setup

Requirements: Python 3.10+ and a Gemini API key (free tier). For the offline Mac mode: Apple Silicon, [Ollama](https://ollama.com) with `qwen3:14b`, ffmpeg. Node 20+ for the Android app.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 -m venv .venv-tts && .venv-tts/bin/pip install mlx-audio 'misaki[en]'   # optional: audio briefing
ollama pull qwen3:14b
```

Private settings go in `.env` (git-ignored, never commit it):

```
SUPABASE_DB_URL=postgresql://postgres.<project-ref>:<password>@aws-1-us-east-1.pooler.supabase.com:5432/postgres
```

The Supabase URL and public key live in `sources.yaml`. Apply the database schema with `python migrate.py`.

### Running

```bash
DIGEST_BACKEND=ollama python run.py   # full daily run: new episodes → summaries → brief, hot topics,
                                      # prices, quiz, audio, forecasts → build site/
python run.py --build-only            # rebuild the site from saved data (no AI)
python run.py --market-only           # refresh prices (fills paper trades, scores predictions)
python run.py --hot-only              # refresh "What's hot" + prices
python run.py --extras-only           # regenerate today's quiz and audio briefing
python run.py --redo [ID ...]         # re-summarize saved episodes from their transcripts
python run.py --claims                # log forecasts for the Scorecard and score due ones
python migrate.py --status            # database migrations: applied / pending
```

Pushing to `main` publishes the site (`.github/workflows/pages.yml`). `scripts/daily.sh` and `scripts/prices.sh` are
the Mac's morning run and market-hours price refresh.

### Running in the cloud (GitHub Actions + Gemini)

`.github/workflows/daily.yml` does the same daily run without the Mac, on Google Gemini's free tier
(`DIGEST_BACKEND=gemini`), in about 30 minutes: Gemini transcribes each episode (`DIGEST_TRANSCRIBE=gemini`, instead
of Whisper) so the quality checks and forecast quotes are still verified against a transcript, then summarizes it;
the audio briefing uses the same Kokoro voice on CPU (`kokoro-onnx`). Models are tried in order (`GEMINI_MODEL`,
then `GEMINI_FALLBACKS`) when one is unavailable, out of quota or slow; requests are paced to `GEMINI_RPM` (8/min).
The free tier allows about 20 requests a day per Flash model, so later episodes are often written by the lite models.
It commits `data/` as market-digest-bot and publishes the site. Transcripts are kept 30 days as a run artifact, not
in the repo.

To turn it on:
1. Repository secrets (Settings → Secrets and variables → Actions): `GEMINI_API_KEY` (from aistudio.google.com) and
   `SUPABASE_DB_URL` (the session-pooler URL, as for the price job).
2. Try it: Actions → Daily digest → Run workflow.
3. Timer: rename `supabase/migrations/016_daily_timer.sql.pending` to `.sql` and run `python migrate.py`. It reuses
   the GitHub token from migration 015 (`scripts/set-dispatch-token.py`) and starts the run at 5:30 am New York time
   on weekdays. A GitHub schedule at 11:41 UTC is the backup and skips itself if the digest is already out.
4. Stop running `scripts/daily.sh` on the Mac, or both will write the day's quiz and audio.

### Android app

```bash
python run.py --build-only
cd mobile && npm install
LIVE_URL=https://stocksplain.app/ npm run sync
cd android && ./gradlew assembleDebug   # → app/build/outputs/apk/debug/app-debug.apk
```

Needs JDK 21 and the Android SDK (`ANDROID_HOME`). Bump `versionCode`/`versionName` in
`mobile/android/app/build.gradle` for each release.

### Layout

| Path | What |
|---|---|
| `run.py` | the daily pipeline and its options |
| `digest/` | sources, transcription, summarizing + quality checks, market data, news, forecasts, voice, site build |
| `templates/` | the website: pages (Jinja), styles, and front-end features |
| `data/` | everything the pipeline produces (summaries, briefs, prices, quizzes, the course) |
| `supabase/migrations/` | database schema, security rules and game logic |
| `mobile/` | the Android app |
