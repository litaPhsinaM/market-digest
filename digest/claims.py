"""Pundit scorecard: pull checkable, dated forecasts out of episodes, then score them when their deadline passes.

Guard rails: every claim must carry a verbatim quote that is found in the transcript (so nobody is credited with
words they never said), a deadline after the episode date, and, for market calls, a symbol we can price.
Market calls are scored automatically from real closing prices; other claims wait for a check.
"""
import datetime as dt
import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from digest import checks, summarize

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "claims.json"

# Plain-English names → symbols we can price.
INDEX_SYMBOLS = {"s&p 500": "^GSPC", "s&p": "^GSPC", "nasdaq": "^IXIC", "dow": "^DJI", "dow jones": "^DJI",
                 "10-year": "^TNX", "10-year treasury yield": "^TNX", "bitcoin": "BTC-USD", "oil": "CL=F", "gold": "GC=F"}
PRICE_KINDS = {"up", "down", "above", "below"}


class Claim(BaseModel):
    speaker: str = Field(description="Who made the forecast, as introduced (e.g. 'Christopher Waller'). Never the show itself.")
    speaker_role: str = Field(description="Their role/affiliation as introduced, e.g. 'Fed governor', 'Bloomberg host', 'CIO at New Edge Wealth'.")
    quote: str = Field(description="The forecast in the speaker's EXACT words from the transcript, 8-40 words, copied character for character.")
    claim: str = Field(description="One plain sentence restating what they predicted.")
    kind: str = Field(description="up | down | above | below | rate_hike | rate_cut | rate_hold | other. "
                                  "up/down = a price will be higher/lower than now; above/below = a price will be above/below a target level.")
    subject: str = Field(description="What it's about: a stock ticker (NVDA), an index or asset name (S&P 500, 10-year, bitcoin, oil, gold), or 'Fed funds rate'.")
    target: float | None = Field(description="Target price/level for above/below claims, else null.")
    deadline: str = Field(description="YYYY-MM-DD by when it should come true, resolved from the episode date (e.g. 'by year end' → Dec 31).")


class Claims(BaseModel):
    claims: list[Claim] = Field(description="0-5 specific, checkable forecasts with a timeframe. Skip vague views ('markets could be volatile'). "
                                            "Empty is fine.")


PROMPT = """From this {kind} ("{title}", {source}, aired {date}), extract forecasts that can later be checked as right or wrong.
Only include a forecast if it names WHAT will happen and BY WHEN (explicitly or clearly implied, e.g. "next month",
"by year end", "at the December meeting"). Copy the quote exactly as it appears in the transcript. Prefer market calls
(prices, indexes, yields) and central bank decisions. Hosts reading the news are not forecasting; skip that.

Transcript:
{transcript}"""


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%$. ]", " ", t.lower())).strip()


def _symbol(subject: str) -> str | None:
    s = subject.strip()
    if s.lower() in INDEX_SYMBOLS:
        return INDEX_SYMBOLS[s.lower()]
    m = re.fullmatch(r"\$?([A-Z]{1,5})", s)
    return m.group(1) if m and checks.valid_ticker(m.group(1)) else None


def extract(item, transcript: str) -> list[dict]:
    words = transcript.split()
    text = " ".join(words[:summarize.MAX_TRANSCRIPT_WORDS])
    out = summarize._generate(PROMPT.format(kind="podcast episode", title=item.title, source=item.source_name,
                                            date=item.published, transcript=text), Claims)
    said = dt.date.fromisoformat(item.published)
    flat, kept = _norm(text), []
    for c in out.claims[:5]:
        if len(c.quote.split()) < 6 or _norm(c.quote) not in flat:
            print(f"    ✂ claim dropped (quote not found in transcript): {c.quote[:60]!r}")
            continue
        try:
            deadline = dt.date.fromisoformat(c.deadline)
        except ValueError:
            continue
        if not (said < deadline <= said + dt.timedelta(days=400)):
            print(f"    ✂ claim dropped (bad deadline {c.deadline}): {c.claim[:60]!r}")
            continue
        kind = c.kind if c.kind in PRICE_KINDS | {"rate_hike", "rate_cut", "rate_hold"} else "other"
        sym = _symbol(c.subject) if kind in PRICE_KINDS else None
        if kind in PRICE_KINDS and not sym:
            kind = "other"  # can't price it automatically
        if kind in {"above", "below"} and c.target is None:
            kind = "other"
        kept.append({
            "id": f"{item.id}-{len(kept)}", "item_id": item.id, "source": item.source_name, "episode": item.title,
            "url": item.url, "said_on": item.published, "speaker": c.speaker.strip(), "role": c.speaker_role.strip(),
            "quote": c.quote.strip(), "claim": c.claim.strip(), "kind": kind, "subject": c.subject.strip(),
            "symbol": sym, "target": c.target, "deadline": deadline.isoformat(), "status": "open",
        })
    return kept


def load() -> list[dict]:
    return json.loads(LEDGER.read_text()) if LEDGER.exists() else []


def save(ledger: list[dict]):
    LEDGER.write_text(json.dumps(ledger, indent=1))


def add(new: list[dict]):
    ledger = [c for c in load() if c["item_id"] not in {n["item_id"] for n in new}]  # re-extraction replaces
    save(ledger + new)
    print(f"    🎙 {len(new)} checkable forecast(s) logged")


def _close_on_or_before(symbol: str, day: dt.date) -> float | None:
    import yfinance as yf
    h = yf.download(symbol, start=(day - dt.timedelta(days=10)).isoformat(), end=(day + dt.timedelta(days=1)).isoformat(),
                    progress=False, auto_adjust=True, timeout=30)
    if h is None or h.empty:
        return None
    close = h["Close"].dropna()
    return float(close.iloc[-1].iloc[0] if hasattr(close.iloc[-1], "iloc") else close.iloc[-1])


def resolve(today: dt.date | None = None):
    """Score market calls whose deadline has passed. Other kinds stay 'awaiting check'."""
    today = today or dt.date.today()
    ledger, changed = load(), 0
    for c in ledger:
        if c["status"] != "open" or dt.date.fromisoformat(c["deadline"]) >= today:
            continue
        if c["kind"] not in PRICE_KINDS:
            c["status"] = "awaiting_check"; changed += 1
            continue
        start = _close_on_or_before(c["symbol"], dt.date.fromisoformat(c["said_on"]))
        end = _close_on_or_before(c["symbol"], dt.date.fromisoformat(c["deadline"]))
        if start is None or end is None:
            continue
        right = {"up": end > start, "down": end < start, "above": end > (c["target"] or 0), "below": end < (c["target"] or 0)}[c["kind"]]
        c.update(status="right" if right else "wrong", start_price=round(start, 4), end_price=round(end, 4),
                 resolved_on=today.isoformat())
        changed += 1
    if changed:
        save(ledger)
        print(f"Scorecard: resolved {changed} forecast(s)")
