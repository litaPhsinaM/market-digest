# Ideas from ZhuLinsen/daily_stock_analysis

Reviewed 2026-11-11. Repo: https://github.com/ZhuLinsen/daily_stock_analysis (70k stars, 57k forks, MIT, very active).
What it is: an LLM "decision dashboard" for traders. It analyses a watchlist every trading day (A-shares, HK, US, JP, KR, TW),
writes buy/sell/watch calls with scores and entry/exit levels, and pushes them to Telegram, Discord, Slack, email or WeChat.
It runs free on GitHub Actions, like ours, and has a web workspace, a strategy chat agent, backtests and alerts.

**Big difference:** it gives trading signals. Market Digest teaches beginners and never gives advice. Borrow the
engineering and the engagement ideas, not the "Buy / Sell, score 65" core.

Status key: [ ] not started · [~] in progress · [x] done

## Worth doing (most value first)

1. [ ] **Push the daily digest to people** (they support Telegram, Discord, Slack, email, ntfy, WeChat).
   For us: a morning "Your 5-minute digest is ready" via email (opt-in, from Supabase), plus browser/app push later.
   Also "your range call scored 84 points" after the close. The biggest engagement lever we don't have yet.
   Effort: M (email first: S).

2. [ ] **Market review block**: market breadth (how many stocks rose vs fell) and sector performance (leading and
   lagging sectors). For us: a "Sectors today" heat strip from the 11 SPDR sector ETFs (XLK, XLF, XLE...), already
   free from Yahoo in the price job, with a one-line "what this means". Teaches that markets move in groups.
   Effort: S.

3. [ ] **Strategy lab (educational backtests)**. They ship classic strategies as small YAML files (moving-average
   golden cross, volume breakout, momentum, low volatility, quality value, dividend blue chips...). For us: a Learn
   page where you pick a classic rule ("buy the S&P when the 50-day average crosses above the 200-day") and see how it
   would have done vs simply buying and holding, with the honest result (usually: buy-and-hold wins, after costs).
   Teaches why most strategies don't beat the index. No advice, all history. Effort: M.

4. [ ] **Backtest our own AI**. They score their past analyses against what prices did next. For us: score the
   Scorecard pundits (done) *and* check the AI summaries' "watch for" items: did the event happen? Shows readers we
   check ourselves. Effort: S–M.

5. [ ] **Price alerts on the watchlist** ("tell me if NVDA moves 5%"). Their alert centre has rules, history and
   delivery. For us: alert rules in Supabase, checked by the 15-minute price job, delivered by #1. Effort: M.

6. [ ] **Tests + CI**. They have ~300 tests and a CI workflow on every push. We have none, and today's audits found
   real bugs (frozen prices, audio never published). Start with tests for checks.py, claims.py (deadlines, quotes),
   hours.py (holidays), the range-game scoring and the build. Effort: S to start.

7. [ ] **A CLAUDE.md / AGENTS.md in the repo** describing the architecture and rules (never give advice, verify
   numbers against transcripts, pull --rebase before pushing, migrations are applied by the owner). Makes every
   future AI-assisted session faster and safer. Effort: S.

8. [ ] **Multi-provider model routing via LiteLLM** (they route Gemini, Claude, OpenAI, DeepSeek, Qwen, Ollama
   through one interface, with channels and fallbacks). For us: only if we add a second paid provider; our own
   Gemini fallback chain covers today's needs. Effort: M.

9. [ ] **Better company news via a search API** (SerpAPI, Tavily, Brave, self-hosted SearXNG). Brave has a free tier.
   For us: richer "headlines" on company sheets than RSS gives. Effort: S–M.

10. [ ] **"Ask about this story" chat**, grounded only in that day's summaries and glossary (their agent chat does
    much more, with tools). Must stay educational and cite the source. Watch the free Gemini quota. Effort: M.

11. [ ] **Social sentiment** (Reddit / X / Polymarket, US stocks) as a "what retail is saying" side note, clearly
    labelled as chatter, not information. Effort: S–M, needs an API key.

## Data sources worth borrowing

Their data layer (`data_provider/`) mixes free and keyed sources. For a US, education-first app:

- [ ] **Economic calendar**: FXMacroData's free public USD endpoints (no key: release calendar, policy-rate history)
  or **FRED** (official, free key). Powers an automatic "Coming up this week: CPI Thu, Fed meeting Dec 17" block, so
  "watch for" comes from real schedules instead of whatever the AI hears on podcasts. Effort: S.
- [ ] **Finnhub** (free key): company news and the earnings calendar for company sheets. Check its terms before
  showing data publicly. Effort: S.
- [ ] **Prediction-market odds** (Polymarket public data, or Kalshi): "markets price an 86% chance of a December hike"
  as a teaching side note. Effort: S–M.
- [ ] **SEC EDGAR** (official, free; not used by them): filings and insider trades for company sheets. Effort: M.
- [ ] Brave Search API (free tier) for news search. Alpha Vantage only as a backup (25 requests/day free).
- Not useful: AkShare, Tushare, Baostock, Pytdx, efinance, Tencent (Chinese markets); Longbridge and Futu (broker accounts).

## Not for us

- Buy / sell / watch calls, scores, entry and exit levels: that's financial advice.
- Chan theory, Elliott waves, "dragon head" and similar A-share trading folklore.
- Sponsor and affiliate model-reseller setups.
- Docker, desktop app, image-to-watchlist import: no need at our size.

## Already similar in Market Digest

- Free scheduled runs on GitHub Actions, trading-day checks (ours: NYSE calendar + database timer).
- Model fallback chain with timeouts (ours: Gemini models in order, then Qwen locally).
- Multi-market price data with Yahoo as the free default.
