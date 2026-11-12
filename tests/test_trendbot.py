"""TrendBot's published rules, tested as a pure function."""
from digest import trendbot


def sig(score, signal, price=100.0):
    return {"score": score, "signal": signal, "trend": "BULL", "bias_pct": 1.0, "volume_ratio": 1.0,
            "macd": "BULLISH", "rsi": 55.0, "price": price}


def test_buys_best_scores_first_up_to_ten_equal_positions():
    signals = {f"S{i:02d}": sig(60 + i, "BUY") for i in range(15)}
    d = trendbot.plan(signals, holdings={}, cash=10_000, prices={s: 100.0 for s in signals})
    buys = [x for x in d if x["action"] == "buy"]
    assert len(buys) == 10
    assert buys[0]["symbol"] == "S14"                                    # highest score first
    assert all(abs(x["qty"] * 100 - 990) < 1 for x in buys)              # ~10% each, 1% kept for price moves


def test_sells_on_sell_signal_and_holds_otherwise():
    signals = {"AAA": sig(15, "STRONG_SELL"), "BBB": sig(50, "WAIT"), "CCC": sig(85, "STRONG_BUY")}
    d = {x["symbol"]: x["action"] for x in trendbot.plan(signals, holdings={"AAA": 5, "BBB": 5}, cash=0, prices={s: 100.0 for s in signals})}
    assert d == {"AAA": "sell", "BBB": "hold"}                           # no cash yet: CCC waits for tomorrow


def test_never_spends_more_cash_than_it_has():
    signals = {f"S{i}": sig(90, "STRONG_BUY") for i in range(10)}
    d = trendbot.plan(signals, holdings={}, cash=2_500, prices={s: 100.0 for s in signals})
    assert sum(x["qty"] * 100 for x in d if x["action"] == "buy") <= 2_500


def test_ignores_watch_and_reduce_for_buying():
    signals = {"W": sig(55, "WAIT"), "R": sig(30, "SELL")}
    assert trendbot.plan(signals, holdings={}, cash=10_000, prices={"W": 100.0, "R": 100.0}) == []


def test_trades_only_individual_stocks():
    s = trendbot.stocks()
    assert "AAPL" in s and "SPY" not in s and "VOO" not in s and len(s) >= 50
