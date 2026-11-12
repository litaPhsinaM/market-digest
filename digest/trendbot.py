"""TrendBot: a robot player that paper-trades with the 100-point checklist from ZhuLinsen/daily_stock_analysis.

Once per trading day, from 3:45 pm New York time, it scores our 61 stocks with their StockTrendAnalyzer
(digest/trendbot_analyzer.py, used unchanged) and trades by fixed, published rules:
  1. Sell every holding the checklist rates SELL or STRONG_SELL.
  2. Buy the highest-scoring BUY / STRONG_BUY stocks it doesn't own, up to 10 holdings of ~10% each,
     using only cash it has now (sale proceeds are spent the next day).
Orders go through the normal engine: they fill at the next real price update, like anyone's.

    python -m digest.trendbot            # only acts on a trading day after 3:45 pm ET, once a day
    python -m digest.trendbot --force    # ignore the time window (testing)
    python -m digest.trendbot --dry-run  # score and plan, write nothing
"""
import argparse
import datetime as dt
import math

BOT_ID = "b07b07b0-7000-4000-8000-00000000b07b"
MAX_HOLDINGS = 10
DECIDE_AFTER = dt.time(15, 45)
BUY = {"STRONG_BUY", "BUY"}
SELL = {"SELL", "STRONG_SELL"}


def stocks() -> list[str]:
    from digest import market
    return [s for s, n in market.UNIVERSE.items() if not any(w in n.lower() for w in ("fund", "etf", "trust", "bitcoin"))]


def score_all(symbols: list[str]) -> dict[str, dict]:
    """Run the upstream analyzer on ~6 months of daily prices for each symbol."""
    import yfinance as yf
    from digest.trendbot_analyzer import StockTrendAnalyzer
    data = yf.download(symbols, period="6mo", interval="1d", group_by="ticker", progress=False, auto_adjust=False, threads=True)
    out = {}
    for sym in symbols:
        try:
            h = data[sym].dropna(subset=["Close"])
            df = h.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low",
                                                 "Close": "close", "Volume": "volume"})[["date", "open", "high", "low", "close", "volume"]]
            if len(df) < 30:
                continue
            r = StockTrendAnalyzer().analyze(df, sym)
            out[sym] = {"score": int(r.signal_score), "signal": r.buy_signal.name, "trend": r.trend_status.name,
                        "bias_pct": round(float(r.bias_ma5), 2), "volume_ratio": round(float(r.volume_ratio_5d), 2),
                        "macd": r.macd_status.name, "rsi": round(float(getattr(r, "rsi_12", 50) or 50), 1),
                        "price": float(df["close"].iloc[-1])}
        except Exception as e:
            print(f"  ! {sym}: {e}")
    return out


def plan(signals: dict[str, dict], holdings: dict[str, float], cash: float, prices: dict[str, float]) -> list[dict]:
    """The published rules, as a pure function (tested in tests/test_trendbot.py)."""
    value = cash + sum(q * prices.get(s, 0) for s, q in holdings.items())
    decisions = []
    sells = [s for s in holdings if signals.get(s, {}).get("signal") in SELL]
    for s in holdings:
        sig = signals.get(s)
        if not sig:
            continue
        if s in sells:
            decisions.append({"symbol": s, "action": "sell", "qty": holdings[s], **sig})
        else:
            decisions.append({"symbol": s, "action": "hold", "qty": holdings[s], **sig})
    slots = MAX_HOLDINGS - (len(holdings) - len(sells))
    per = value / MAX_HOLDINGS
    candidates = sorted((s for s, g in signals.items() if g["signal"] in BUY and s not in holdings),
                        key=lambda s: (-signals[s]["score"], s))
    for s in candidates:
        if slots <= 0 or cash < per * 0.5:
            break
        spend = min(per, cash) * 0.99  # a little room for the price moving before the fill
        qty = math.floor(spend / prices[s] * 1e6) / 1e6
        if qty <= 0:
            continue
        decisions.append({"symbol": s, "action": "buy", "qty": qty, **signals[s]})
        cash -= qty * prices[s]
        slots -= 1
    return decisions


def run(force: bool = False, dry: bool = False):
    from digest import hours, supa
    now = dt.datetime.now(hours.NY)
    today = now.date()
    if not force and not (hours.session(today) and now.time() >= DECIDE_AFTER):
        print(f"TrendBot: not trading now ({now:%a %H:%M} ET; it decides after 3:45 pm on trading days)")
        return
    import psycopg
    with psycopg.connect(supa._db_url(), connect_timeout=20) as c:
        if not force and c.execute("select 1 from public.bot_decisions where day = %s limit 1", (today,)).fetchone():
            print("TrendBot: already traded today")
            return
        if c.execute("select 1 from public.orders where user_id = %s and status = 'pending' limit 1", (BOT_ID,)).fetchone():
            print("TrendBot: yesterday's orders haven't filled yet; waiting")
            return
        cash = float(c.execute("select cash from public.portfolios where user_id = %s", (BOT_ID,)).fetchone()[0])
        holdings = {s: float(q) for s, q in c.execute(
            "select symbol, sum(case when side = 'buy' then qty else -qty end) from public.orders "
            "where user_id = %s and status = 'filled' group by 1 having sum(case when side = 'buy' then qty else -qty end) > 0.000001",
            (BOT_ID,)).fetchall()}
        universe = sorted(set(stocks()) | set(holdings))
        signals = score_all(universe)
        prices = {s: g["price"] for s, g in signals.items()}
        decisions = plan(signals, holdings, cash, prices)
        buys = [d for d in decisions if d["action"] == "buy"]
        sells = [d for d in decisions if d["action"] == "sell"]
        print(f"TrendBot {today}: scored {len(signals)} stocks; cash ${cash:,.2f}; holds {len(holdings)}; "
              f"sell {[d['symbol'] for d in sells]}; buy {[d['symbol'] for d in buys]}")
        if dry:
            for d in sorted(decisions, key=lambda d: -d["score"]):
                print(f"  {d['action']:4} {d['symbol']:6} score {d['score']:3} {d['signal']:12} trend {d['trend']}")
            return
        with c.transaction():
            for d in sells + buys:  # sells first, so their orders sit ahead in the queue
                c.execute("insert into public.orders (user_id, symbol, side, qty, note) values (%s, %s, %s, %s, %s)",
                          (BOT_ID, d["symbol"], d["action"], d["qty"], f"TrendBot score {d['score']} ({d['signal']})"))
            for d in decisions:
                c.execute("""insert into public.bot_decisions (day, symbol, action, score, signal, trend, bias_pct, volume_ratio,
                                                               macd, rsi, qty, price)
                             values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                             on conflict (day, symbol) do nothing""",
                          (today, d["symbol"], d["action"], d["score"], d["signal"], d["trend"], d["bias_pct"],
                           d["volume_ratio"], d["macd"], d["rsi"], d["qty"], d["price"]))
            if not decisions:  # remember that today was decided even when it did nothing
                c.execute("insert into public.bot_decisions (day, symbol, action, score, signal) values (%s, '-', 'hold', 0, 'NONE') "
                          "on conflict do nothing", (today,))
        print(f"TrendBot: placed {len(sells)} sell and {len(buys)} buy orders; they fill at the next price update")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(force=a.force, dry=a.dry_run)
