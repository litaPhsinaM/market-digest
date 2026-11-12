# Ideas from ZhuLinsen/daily_stock_analysis

Reviewed 2026-11-11. Repo: https://github.com/ZhuLinsen/daily_stock_analysis (70k stars, 57k forks, MIT, very active).
What it is: an LLM "decision dashboard" for traders. It analyses a watchlist every trading day (A-shares, HK, US, JP, KR, TW),
writes buy/sell/watch calls with scores and entry/exit levels, and pushes them to Telegram, Discord, Slack, email or WeChat.
It runs free on GitHub Actions, like ours, and has a web workspace, a strategy chat agent, backtests and alerts.

**Big difference:** it gives trading signals. Market Digest teaches beginners and never gives advice. Borrow the
engineering and the engagement ideas, not the "Buy / Sell, score 65" core.

Status key: [ ] not started · [~] in progress · [x] done

## The list (in order: quick safety wins, then the biggest user value)

1. [x] **A CLAUDE.md / AGENTS.md in the repo** describing the architecture and rules (never give advice, verify
   numbers against transcripts, pull --rebase before pushing, migrations are applied by the owner). Makes every
   future AI-assisted session faster and safer. Effort: S.

2. [x] **Tests + CI**. They have ~300 tests and a CI workflow on every push. We have none, and today's audits found
   real bugs (frozen prices, audio never published). Start with tests for checks.py, claims.py (deadlines, quotes),
   hours.py (holidays), the range-game scoring and the build. Effort: S to start.

3. [ ] **Economic calendar** (data source). FXMacroData's free public USD endpoints (no key: release calendar,
   policy-rate history) or **FRED** (official, free key). Powers an automatic "Coming up this week: CPI Thu, Fed
   meeting Dec 17" block, so "watch for" comes from real schedules instead of whatever the AI hears on podcasts.
   Effort: S.

4. [ ] **Sectors today** (their "market review"): market breadth (how many stocks rose vs fell) and sector
   performance. For us: a heat strip from the 11 SPDR sector ETFs (XLK, XLF, XLE...), free from Yahoo in the price
   job, with a one-line "what this means". Teaches that markets move in groups. Effort: S.

5. [ ] **Push the daily digest to people** (they support Telegram, Discord, Slack, email, ntfy, WeChat).
   For us: a morning "Your 5-minute digest is ready" via email (opt-in, from Supabase), plus browser/app push later.
   Also "your range call scored 84 points" after the close. The biggest engagement lever we don't have yet.
   Effort: M (email first: S).

6. [ ] **Finnhub company news + earnings calendar** (data source, free key) for company sheets. Check its terms
   before showing data publicly. Effort: S.

7. [ ] **Prediction-market odds** (Polymarket public data, or Kalshi): "markets price an 86% chance of a December
   hike" as a teaching side note next to the economic calendar. Effort: S–M.

8. [ ] **Strategy lab (educational backtests)**. They ship classic strategies as small YAML files (moving-average
   golden cross, volume breakout, momentum, low volatility, quality value, dividend blue chips...). For us: a Learn
   page where you pick a classic rule ("buy the S&P when the 50-day average crosses above the 200-day") and see how it
   would have done vs simply buying and holding, with the honest result (usually: buy-and-hold wins, after costs).
   Teaches why most strategies don't beat the index. No advice, all history. Effort: M.

9. [ ] **Backtest our own AI**. They score their past analyses against what prices did next. For us: the Scorecard
   already checks pundits; also check the AI summaries' "watch for" items: did the event happen? Effort: S–M.

10. [ ] **Price alerts on the watchlist** ("tell me if NVDA moves 5%"). Alert rules in Supabase, checked by the
    15-minute price job, delivered by #5. Effort: M.

11. [ ] **SEC EDGAR filings and insider trades** (official, free; they don't use it) on company sheets. Effort: M.

12. [ ] **Better news search** via Brave Search API (free tier); SerpAPI, Tavily or self-hosted SearXNG as
    alternatives. Richer "headlines" than RSS. Effort: S–M.

13. [ ] **"Ask about this story" chat**, grounded only in that day's summaries and glossary. Must stay educational
    and cite the source. Watch the free Gemini quota. Effort: M.

14. [ ] **Social sentiment** (Reddit / X, US stocks) as a "what retail is saying" side note, clearly labelled as
    chatter, not information. Effort: S–M, needs an API key.

15. [ ] **Multi-provider model routing via LiteLLM** (Gemini, Claude, OpenAI, DeepSeek, Qwen, Ollama through one
    interface). Only if we add a second paid provider; our Gemini fallback chain covers today. Effort: M.


16. [~] **🤖 TrendBot: a robot player on the leaderboard** that paper-trades daily with their exact 100-point technical
    rules (src/stock_analyzer.py: trend 30 = MA5>MA10>MA20 alignment, bias 20 = distance from MA5 / "don't chase
    above 5%", volume 15 = volume vs 5-day average, MACD 15, support 10, RSI 10). It competes with players and the
    S&P 500 using real prices. Teaches whether a famous trading formula beats beginners or the index. Pure experiment,
    no advice. Effort: M.

17. [ ] **📈 "Chart check" on company sheets**: the same indicators (trend, RSI, MACD, volume ratio) explained in plain
    English ("RSI 68: it has risen fast; traders call this nearly 'overbought'"), never as buy/sell. Effort: S–M.

How their AAPL screen is made (checked in their code, 2026-11-11): prices, volume and P/E from Yahoo; the "Watch 59"
score is the 100-point checklist above (plain maths); an LLM only writes the "Key insights" prose from those numbers,
and that prose gives advice ("investors should avoid chasing highs..."), which we must never do.

Their data sources we can't use: AkShare, Tushare, Baostock, Pytdx, efinance, Tencent (Chinese markets); Longbridge
and Futu (broker accounts). Alpha Vantage only as a last-resort backup (25 requests/day free).

## Not for us

- Buy / sell / watch calls, scores, entry and exit levels: that's financial advice.
- Chan theory, Elliott waves, "dragon head" and similar A-share trading folklore.
- Sponsor and affiliate model-reseller setups.
- Docker, desktop app, image-to-watchlist import: no need at our size.

## Already similar in Market Digest

- Free scheduled runs on GitHub Actions, trading-day checks (ours: NYSE calendar + database timer).
- Model fallback chain with timeouts (ours: Gemini models in order, then Qwen locally).
- Multi-market price data with Yahoo as the free default.
