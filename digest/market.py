"""Daily market snapshot: index strip + company cards (price history, key stats, headlines). Free, via yfinance."""
import datetime as dt
import math
import re

import yfinance as yf

INDICES = [
    ("^GSPC", "S&P 500", "The 500 biggest US companies. When people say 'the market', they usually mean this."),
    ("^IXIC", "Nasdaq", "Tech-heavy index of 3,000+ stocks on the Nasdaq exchange (Apple, Nvidia, Microsoft…)."),
    ("^DJI", "Dow Jones", "30 large, famous US companies. Old and narrow, but still quoted on the news daily."),
    ("^TNX", "10-yr Treasury", "Interest rate the US government pays to borrow for 10 years. Drives mortgage rates and stock valuations."),
    ("BTC-USD", "Bitcoin", "The largest cryptocurrency, often treated as a gauge of investors' appetite for risk."),
]


def tickers_from_summaries(items: list[dict]) -> dict[str, list[str]]:
    """Map ticker -> ids of items that discuss it. Accepts 'Nvidia (NVDA)' or bare 'NVDA'."""
    found = {}
    for it in items:
        for raw in it["summary"]["tickers"]:
            m = re.search(r"\(([A-Z][A-Z.\-]{0,6})\)", raw) or re.fullmatch(r"\s*([A-Z][A-Z.\-]{0,6})\s*", raw)
            if m:
                found.setdefault(m.group(1), []).append(it["id"])
    return found


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def _series(close):
    close = close.dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in close.items()]


def _news(t, limit=3):
    out = []
    for n in (t.news or [])[:limit]:
        c = n.get("content", n)
        url = (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url")
        if c.get("title") and url:
            out.append({"title": c["title"], "source": (c.get("provider") or {}).get("displayName", ""),
                        "url": url, "date": (c.get("pubDate") or "")[:10]})
    return out


def snapshot(tickers: list[str]) -> dict:
    symbols = [s for s, _, _ in INDICES] + tickers
    hist = yf.download(symbols, period="1y", interval="1d", auto_adjust=True, progress=False)["Close"]

    def quote(sym):
        if sym not in hist or hist[sym].dropna().empty:
            return None
        s = _series(hist[sym])
        last, prev = s[-1][1], s[-2][1] if len(s) > 1 else s[-1][1]
        return {"symbol": sym, "price": last, "change": last - prev,
                "change_pct": (last / prev - 1) * 100 if prev else 0, "history": s}

    indices = []
    for sym, name, explain in INDICES:
        q = quote(sym)
        if q:
            indices.append({**q, "name": name, "explain": explain})

    companies = []
    for sym in tickers:
        q = quote(sym)
        if not q:  # unlisted (e.g. pre-IPO) or bad ticker
            continue
        t = yf.Ticker(sym)
        try:
            info = t.info
        except Exception:
            info = {}
        try:
            cal = t.calendar or {}
            earn = cal.get("Earnings Date") or []
            next_earn = earn[0].isoformat() if earn else None
        except Exception:
            next_earn = None
        companies.append({
            **q, "name": info.get("shortName") or info.get("longName") or sym,
            "exchange": info.get("fullExchangeName") or info.get("exchange", ""),
            "sector": info.get("sector"), "website": info.get("website"),
            "stats": {
                "open": _num(info.get("open")), "high": _num(info.get("dayHigh")), "low": _num(info.get("dayLow")),
                "market_cap": _num(info.get("marketCap")), "pe": _num(info.get("trailingPE")),
                "dividend_yield": _num(info.get("dividendYield")),
                "high_52w": _num(info.get("fiftyTwoWeekHigh")), "low_52w": _num(info.get("fiftyTwoWeekLow")),
            },
            "next_earnings": next_earn,
            "news": _news(t),
        })
    return {"as_of": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "indices": indices, "companies": companies}
