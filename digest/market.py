"""Daily market snapshot: index strip + company cards (price history, key stats, headlines). Free, via yfinance."""
import concurrent.futures
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


_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def _with_timeout(fn, secs: int = 30):
    """Yahoo calls occasionally hang for many minutes; give up on any single call after `secs`."""
    return _pool.submit(fn).result(timeout=secs)


_GENERIC = {"inc", "corp", "corporation", "company", "co", "the", "group", "holdings", "ltd", "plc", "class", "trust", "fund", "etf"}


def name_matches(company_name: str, text: str) -> bool:
    """True if the company's distinctive name word appears in text, e.g. 'NVIDIA Corporation' in a story about Nvidia.
    Guards against models guessing a real ticker that belongs to a different company."""
    words = [w for w in re.findall(r"[a-z0-9&]+", company_name.lower()) if w not in _GENERIC and len(w) > 1]
    return bool(words) and re.search(r"\b" + re.escape(words[0]), text.lower()) is not None


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


def _safe_news(t):
    try:
        return _with_timeout(lambda: _news(t))
    except Exception:
        return []


def snapshot(tickers: list[str]) -> dict:
    symbols = [s for s, _, _ in INDICES] + tickers
    hist = yf.download(symbols, period="1y", interval="1d", auto_adjust=True, progress=False, timeout=30)["Close"]

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

    def company(sym):
        q = quote(sym)
        if not q:  # unlisted (e.g. pre-IPO) or bad ticker
            return None
        t = yf.Ticker(sym)
        try:
            info = _with_timeout(lambda: t.info)
        except Exception:
            info = {}
        try:
            cal = _with_timeout(lambda: t.calendar) or {}
            earn = cal.get("Earnings Date") or []
            next_earn = earn[0].isoformat() if earn else None
        except Exception:
            next_earn = None
        return {
            **q, "name": info.get("shortName") or info.get("longName") or sym,
            "quote_type": info.get("quoteType"),
            "exchange": info.get("fullExchangeName") or info.get("exchange", ""),
            "sector": info.get("sector"), "website": info.get("website"),
            "stats": {
                "open": _num(info.get("open")), "high": _num(info.get("dayHigh")), "low": _num(info.get("dayLow")),
                "market_cap": _num(info.get("marketCap")), "pe": _num(info.get("trailingPE")),
                "dividend_yield": _num(info.get("dividendYield")),
                "high_52w": _num(info.get("fiftyTwoWeekHigh")), "low_52w": _num(info.get("fiftyTwoWeekLow")),
            },
            "next_earnings": next_earn,
            "news": _safe_news(t),
        }

    # Fetch companies in parallel (each needs 3 Yahoo calls); a separate pool avoids nesting in _pool.
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        companies = [c for c in ex.map(company, tickers) if c]
    return {"as_of": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
            "indices": indices, "companies": companies, "movers": movers()}


def movers(count: int = 5) -> dict:
    """Biggest US gainers/losers and most-traded stocks today (large enough to matter: > $2B market cap)."""
    out = {}
    for key in ("day_gainers", "day_losers", "most_actives"):
        try:
            quotes = _with_timeout(lambda: yf.screen(key, count=count * 3)["quotes"])
        except Exception as e:
            print(f"! movers {key}: {e!r}")
            continue
        out[key] = [{"symbol": q["symbol"], "name": q.get("shortName") or q["symbol"],
                     "price": q.get("regularMarketPrice"), "change_pct": q.get("regularMarketChangePercent", 0),
                     "change": q.get("regularMarketChange", 0)}
                    for q in quotes if (q.get("marketCap") or 0) > 2e9][:count]
    return out
