"""Daily market snapshot: index strip + company cards (price history, key stats, headlines). Free, via yfinance."""
import concurrent.futures
from zoneinfo import ZoneInfo
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


# Index funds: always tradable in the paper-trading game so learners can try "just buy the market".
FUNDS = ["SPY", "QQQ", "VTI"]
FUND_NAMES = ["S&P 500 index fund (SPY)", "Nasdaq-100 index fund (QQQ)", "Total US market fund (VTI)"]

# Always-tradable list for paper trading (beyond the funds above and the companies in today's news).
UNIVERSE = {
    # funds & ETFs
    "VOO": "S&P 500 fund (Vanguard)", "IWM": "Small US companies fund", "DIA": "Dow Jones 30 fund", "SCHD": "US dividend stocks fund",
    "VXUS": "International stocks fund", "BND": "US bond fund", "TLT": "Long-term US Treasury bond fund", "GLD": "Gold fund",
    "XLK": "Tech sector fund", "XLF": "Financials sector fund", "XLE": "Energy sector fund", "XLV": "Healthcare sector fund",
    # popular stocks
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "GOOGL": "Alphabet (Google)", "AMZN": "Amazon", "META": "Meta Platforms",
    "TSLA": "Tesla", "BRK-B": "Berkshire Hathaway", "AVGO": "Broadcom", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "LLY": "Eli Lilly", "JNJ": "Johnson & Johnson", "PFE": "Pfizer", "MRK": "Merck", "ABBV": "AbbVie",
    "XOM": "Exxon Mobil", "CVX": "Chevron", "PG": "Procter & Gamble", "KO": "Coca-Cola", "PEP": "PepsiCo", "MCD": "McDonald's",
    "SBUX": "Starbucks", "NKE": "Nike", "DIS": "Disney", "NFLX": "Netflix", "COST": "Costco", "WMT": "Walmart", "TGT": "Target",
    "HD": "Home Depot", "LOW": "Lowe's", "AMD": "AMD", "INTC": "Intel", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe", "IBM": "IBM", "CSCO": "Cisco", "UBER": "Uber", "ABNB": "Airbnb",
    "SHOP": "Shopify", "PYPL": "PayPal", "COIN": "Coinbase", "PLTR": "Palantir", "SNOW": "Snowflake", "SPOT": "Spotify",
    "BAC": "Bank of America", "WFC": "Wells Fargo", "GS": "Goldman Sachs", "MS": "Morgan Stanley", "AXP": "American Express",
    "BA": "Boeing", "CAT": "Caterpillar", "GE": "GE Aerospace", "F": "Ford", "GM": "General Motors", "T": "AT&T", "VZ": "Verizon",
}


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
    symbols = list(dict.fromkeys([s for s, _, _ in INDICES] + ["^VIX"] + FUNDS + tickers + list(UNIVERSE)))
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
    # Market time (New York), the same wherever this runs (Mac or cloud).
    return {"as_of": dt.datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="minutes"),
            "indices": indices, "companies": companies, "movers": movers(),
            "mood": mood(quote("^GSPC"), quote("^VIX")),
            "funds": [{**q, "name": n} for f, n in zip(FUNDS, FUND_NAMES) if (q := quote(f))],
            # price-only quotes (no history) keep the snapshot small; the game reads history from the database
            "universe": [{"symbol": sym, "name": name, "price": q["price"], "change_pct": q["change_pct"]}
                         for sym, name in UNIVERSE.items() if (q := quote(sym))]}


def mood(spx, vix):
    """A simple fear/greed score (0-100) from three public signals. Our own gauge, kept deliberately transparent."""
    if not spx or not vix:
        return None
    clamp = lambda v: max(0.0, min(100.0, v))
    hist = [p[1] for p in spx["history"]]
    month = (hist[-1] / hist[-23] - 1) * 100 if len(hist) > 23 else 0
    parts = [
        {"name": "Today's S&P 500 move", "value": f"{spx['change_pct']:+.2f}%", "score": clamp(50 + spx["change_pct"] * 25)},
        {"name": "S&P 500 past month", "value": f"{month:+.1f}%", "score": clamp(50 + month * 10)},
        {"name": "VIX (expected volatility)", "value": f"{vix['price']:.1f}", "score": clamp((30 - vix["price"]) / 17 * 100)},
    ]
    score = round(sum(p["score"] for p in parts) / len(parts))
    label = next(l for cut, l in ((20, "Extreme fear"), (40, "Fear"), (60, "Neutral"), (80, "Greed"), (101, "Extreme greed")) if score < cut)
    return {"score": score, "label": label, "parts": parts}


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
