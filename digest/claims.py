"""Pundit scorecard: pull checkable, dated forecasts out of episodes, then score them when their deadline passes.

Guard rails: every claim must carry a verbatim quote that is found in the transcript (so nobody is credited with
words they never said), a deadline after the episode date, and, for market calls, a symbol we can price.
Market calls are scored automatically from real closing prices; other claims wait for a check.
"""
import datetime as dt
import difflib
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
    deadline_said: str = Field(description="The timeframe in the speaker's words, e.g. 'by year end', 'next year', 'at the December meeting', 'not specified'.")
    deadline: str = Field(description="YYYY-MM-DD by when it should come true, worked out from the episode date (e.g. 'by year end' → Dec 31), or 'none'.")


class Claims(BaseModel):
    claims: list[Claim] = Field(description="0-5 specific, checkable forecasts with a timeframe. Skip vague views ('markets could be volatile'). "
                                            "Empty is fine.")


PROMPT = """From this {kind} ("{title}", {source}, aired {date}), extract forecasts that can later be checked as right or wrong.
A forecast is the SPEAKER'S OWN prediction about the FUTURE ("I expect the Fed to hike in December", "stocks will
be higher by year end"). Skip all of these, they are NOT forecasts:
- facts or data that already happened ("inflation came in hot", "the yield jumped 20 basis points", "the stock is off 30%")
- descriptions of the present ("the AI trade is the main driver", "the IPO is oversubscribed", "the economy is weak")
- decisions or schedules already announced, reported by a host or reporter ("it is expected to start trading next week")
- what other people hope or plan ("negotiators are hoping for a deal")
- vague moods with nothing to check ("the next couple of years will be ugly")
List each forecast once.
Only include a forecast if it names WHAT will happen and BY WHEN (explicitly or clearly implied, e.g. "next month",
"by year end", "at the December meeting"). Copy the quote exactly as it appears in the transcript. Prefer market calls
(prices, indexes, yields) and central bank decisions. Hosts reading the news are not forecasting; skip that.

Transcript:
{transcript}"""


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%$. ]", " ", t.lower())).strip()


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def _month_end(y: int, m: int) -> dt.date:
    return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))


def resolve_deadline(iso: str, said: str, said_on: dt.date) -> dt.date | None:
    """Turn the model's deadline (ISO date or words like 'next year', 'December', 'early 2028') into a date, or None."""
    try:
        d = dt.date.fromisoformat(iso.strip()[:10])
        if d > said_on:
            return d
    except ValueError:
        pass
    t = f"{iso} {said}".lower()
    y = said_on.year
    if re.search(r"next week", t): return said_on + dt.timedelta(days=7)
    if re.search(r"next month", t): return _month_end(y + (said_on.month == 12), said_on.month % 12 + 1)
    if re.search(r"next year", t): return dt.date(y + 1, 12, 31)
    if re.search(r"(this|the) year|year[- ]end|end of (the )?year|by december", t): return dt.date(y, 12, 31)
    m = re.search(r"\b(early|mid|late)?[- ]?(20\d\d)\b", t)
    if m and int(m.group(2)) >= y:
        yr = int(m.group(2))
        return {"early": dt.date(yr, 3, 31), "mid": dt.date(yr, 6, 30)}.get(m.group(1), dt.date(yr, 12, 31))
    q = re.search(r"\b(q[1-4]|first|second|third|fourth) quarter|\bq([1-4])\b", t)
    if q:
        n = {"first": 1, "second": 2, "third": 3, "fourth": 4}.get((q.group(1) or "").split()[0], None) or int(re.sub(r"\D", "", q.group(0)) or 4)
        d = _month_end(y, n * 3)
        return d if d > said_on else _month_end(y + 1, n * 3)
    for i, name in enumerate(MONTHS, start=1):
        if re.search(rf"\b{name}\b", t):
            d = _month_end(y, i)
            return d if d > said_on else _month_end(y + 1, i)
    return None


def infer_kind(model_kind: str, text: str) -> str:
    k, t = model_kind.lower(), text.lower()
    if k in PRICE_KINDS | {"rate_hike", "rate_cut", "rate_hold"}:
        return k
    fed = re.search(r"\b(fed|federal reserve|fomc|central bank|ecb|bank of (england|japan|canada)|rate)s?\b", t)
    if fed and re.search(r"\b(rate hikes?|hike rates|raise rates|tighten(ing)?)\b", t): return "rate_hike"
    if fed and re.search(r"\b(rate cuts?|cut rates|lower rates|eas(e|ing))\b", t): return "rate_cut"
    if fed and re.search(r"\b((hold|pause|keep) rates|on hold)\b", t): return "rate_hold"
    if re.search(r"\b(above|over|at least) [\d$]", t): return "above"
    if re.search(r"\b(below|under) [\d$]", t): return "below"
    if re.search(r"higher|rise|rally|rebound|go up|gain|climb|bull", t): return "up"
    if re.search(r"lower|fall|drop|decline|selloff|sell-off|go down|bear", t): return "down"
    return "other"


def quote_in(quote: str, flat: str) -> bool:
    """Exact match, or ≥85% similar to some stretch of the transcript (models often change a word or two)."""
    q = _norm(quote)
    if q in flat:
        return True
    qw, fw = q.split(), flat.split()
    n = len(qw)
    if n < 6:
        return False
    first = set(qw[:3])
    best = 0.0
    for i in range(len(fw) - n + 1):
        if fw[i] in first:
            best = max(best, difflib.SequenceMatcher(None, qw, fw[i:i + n]).ratio())
            if best >= 0.85:
                return True
    return False


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
    flat, kept, seen = _norm(text), [], set()
    for c in out.claims[:5]:
        key = _norm(c.claim)
        if key in seen:  # models sometimes list the same forecast twice
            continue
        seen.add(key)
        if len(c.quote.split()) < 6 or not quote_in(c.quote, flat):
            print(f"    ✂ claim dropped (quote not found in transcript): {c.quote[:60]!r}")
            continue
        deadline = resolve_deadline(c.deadline, c.deadline_said, said)
        if deadline is None:
            print(f"    · skipped (no checkable deadline): {c.claim[:60]!r}")
            continue
        if not (said < deadline <= said + dt.timedelta(days=800)):
            print(f"    ✂ claim dropped (bad deadline {c.deadline}): {c.claim[:60]!r}")
            continue
        kind = infer_kind(c.kind, c.claim + " " + c.quote)
        sym = _symbol(c.subject) if kind in PRICE_KINDS else None
        if kind in PRICE_KINDS and not sym:
            kind = "other"  # can't price it automatically
        if c.target is not None and 1900 <= c.target <= 2100 and float(c.target).is_integer() and str(int(c.target)) in c.deadline_said + c.deadline:
            c.target = None  # the model put the deadline year in the target field
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
