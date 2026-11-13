"""Deterministic quality checks on model output. Cheap (no model calls) and they catch the errors models actually make:
invented figures, wrong or made-up tickers, advice wording, generic headlines, and hot topics padded with unrelated headlines."""
import re
import time
import urllib.request
from pathlib import Path

REF = Path(__file__).resolve().parent.parent / "data" / "ref"
SYMBOL_FILES = {  # Nasdaq's official directory of every US-listed symbol, with an ETF flag
    "nasdaqlisted.txt": {"symbol": 0, "etf": 6, "test": 3},
    "otherlisted.txt": {"symbol": 0, "etf": 4, "test": 6},
}

_stocks = None


def listed_stocks() -> set[str]:
    """Symbols of US-listed operating companies (ETFs and test issues excluded). Refreshed weekly."""
    global _stocks
    if _stocks is not None:
        return _stocks
    REF.mkdir(parents=True, exist_ok=True)
    _stocks = set()
    for name, col in SYMBOL_FILES.items():
        path = REF / name
        if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
            try:
                with urllib.request.urlopen(f"https://www.nasdaqtrader.com/dynamic/SymDir/{name}", timeout=30) as r:
                    path.write_bytes(r.read())
            except Exception as e:
                print(f"! could not refresh {name}: {e}")
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            p = line.split("|")
            if len(p) > max(col.values()) and p[col["etf"]] != "Y" and p[col["test"]] != "Y":
                _stocks.add(p[col["symbol"]])
    return _stocks


def valid_ticker(sym: str) -> bool:
    stocks = listed_stocks()
    return not stocks or sym.upper() in stocks  # if the list couldn't load, don't block everything


# ---------- item summaries ----------

GENERIC_HEADLINE = re.compile(r"\b(key (market|business)|market (dynamics|updates|volatility)|updates from|insights|a look at)\b", re.I)
ADVICE = re.compile(r"\b(investors? should|you should|should consider|be cautious|cautionary tale|it'?s wise to)\b", re.I)
RECAP_LESSON = re.compile(r"^\s*(this|the) (episode|video|podcast|story|discussion)\b|highlights the importance", re.I)


def _num_tokens(text: str) -> list[str]:
    """Core numbers in a figure, e.g. '-$108.6 billion' -> ['108.6'], '1,000%' -> ['1000']."""
    return [n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)]


def check_item(summary: dict, transcript: str) -> list[str]:
    """Fix what can be fixed deterministically (in place) and return problems that need a model repair."""
    flat = re.sub(r"(?<=\d),(?=\d)", "", transcript)
    problems = []

    # Figures must actually appear in the transcript; invented years are a known failure.
    kept = []
    for n in summary["numbers"]:
        nums = _num_tokens(n["figure"])
        years = [y for y in re.findall(r"\b(?:19|20)\d\d\b", n["figure"] + " " + n["context"]) if y not in flat]
        if (nums and not all(x in flat for x in nums)) or years:
            print(f"    ✂ dropped figure not in transcript: {n['figure']} ({n['context'][:50]})")
            continue
        kept.append(n)
    summary["numbers"] = kept

    # Dates and numbers written anywhere in the prose must come from the source (models mix up nearby dates).
    MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
    prose = {"tldr": summary["tldr"], "key points": " ".join(k["point"] + " " + k["why_it_matters"] for k in summary["key_points"]),
             "opinions": " ".join(summary["opinions_and_predictions"]), "segments": " ".join(summary.get("segments", []))}
    for field, text in prose.items():
        for d in re.findall(rf"\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?\b", text):
            month, day = d.split()[0], re.sub(r"\D", "", d.split()[1])
            if not re.search(rf"{month}\s+{day}(?:st|nd|rd|th)?\b", transcript):
                problems.append(f"{field} says {d!r}, which the source never says. Remove that date or use the source's wording "
                                f"(e.g. 'next Wednesday').")
        for n in set(_num_tokens(text)):
            if len(n.replace(".", "")) >= 2 and n not in flat:
                problems.append(f"{field} contains the number {n}, which isn't in the source. Remove it.")

    # Tickers: keep 'Name (TICKER)' only for real listed stocks; otherwise keep just the name.
    fixed = []
    for raw in summary["tickers"]:
        bare = re.fullmatch(r"\s*([A-Z][A-Z.\-]{0,6})\s*", raw)
        if bare and not valid_ticker(bare.group(1)):
            print(f"    ✂ invalid ticker {bare.group(1)}")
            continue
        m = re.search(r"\(([A-Z][A-Z.\-]{0,6})\)", raw)
        if m and not valid_ticker(m.group(1)):
            name = raw[:m.start()].strip()
            if valid_ticker(name):  # written backwards, e.g. 'NVDA (NVIDIA)'
                raw = f"{m.group(1).title()} ({name})"
            else:
                print(f"    ✂ invalid ticker {m.group(1)} → '{name}'")
                raw = name
        if raw and raw not in fixed:
            fixed.append(raw)
    summary["tickers"] = fixed

    if GENERIC_HEADLINE.search(summary["headline"]):
        problems.append(f"headline is generic: {summary['headline']!r}. Name the main subject(s) concretely.")
    if RECAP_LESSON.search(summary["lesson"]) or re.search(r"\b(investors?|should)\b", summary["lesson"], re.I):
        problems.append(f"lesson is a recap or gives advice: {summary['lesson']!r}. Write a reusable cause → effect principle.")
    for field in ("tldr", "lesson"):
        if ADVICE.search(summary[field]):
            problems.append(f"{field} gives advice ({ADVICE.search(summary[field]).group(0)!r}). Describe, don't prescribe.")
    if re.search(r"\bthis (digest|summary)\b|^\s*(this|the) (episode|video|podcast) (covers|provides|discusses)", summary["quality_note"], re.I):
        problems.append(f"quality_note describes the summary: {summary['quality_note']!r}. Say who speaks (reporter, analyst, "
                        f"executive, investor with a stake) and whether claims are data-backed or speculation.")
    return problems


# ---------- hot topics ----------

_STOP = {"the", "and", "for", "with", "from", "into", "over", "after", "amid", "says", "said", "its", "their", "this", "that",
         "what", "why", "how", "new", "more", "than", "as", "to", "of", "in", "on", "a", "an", "is", "are", "be", "by", "at"}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$%.\-']+", text.lower()) if len(w) > 2 and w not in _STOP}


def check_hot(topics: list[dict], headlines: dict[str, dict]) -> list[dict]:
    """Keep only headlines that share a keyword with their topic; drop topics left with fewer than 2."""
    out, used = [], set()
    for t in topics:
        keys = _keywords(t["title"])
        ids = []
        for i in dict.fromkeys(t["headline_ids"]):
            h = headlines.get(i)
            if h and i not in used and keys & _keywords(h["title"] + " " + h["blurb"]):
                ids.append(i)
        ids = ids[:5]
        dropped = len(t["headline_ids"]) - len(ids)
        if len(ids) < 2:
            print(f"  ✂ dropped hot topic with too little support: {t['title']!r}")
            continue
        if dropped:
            print(f"  ✂ {t['title'][:50]!r}: removed {dropped} unrelated headline(s)")
        used.update(ids)
        t["headline_ids"] = ids
        t["tickers"] = [s for s in dict.fromkeys(x.strip().upper() for x in t["tickers"]) if valid_ticker(s)]
        out.append(t)
    return out


# ---------- name spellings ----------
# Audio transcription mangles names ("Collette Kress", "Colet Kress" for Colette Kress). Newsroom headlines spell them
# correctly, so a two-word name in a summary that is one or two letters off a name in today's headlines (same first
# OR last word, the other word very close) is rewritten to the headline spelling.
_NAME = re.compile(r"(?=\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b)")  # lookahead: overlapping pairs


def _near(a: str, b: str) -> bool:
    import difflib
    return a != b and a[0] == b[0] and difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8


def name_fixes(texts: list[str], reference: list[str]) -> dict[str, str]:
    known = {f"{m.group(1)} {m.group(2)}" for t in reference for m in _NAME.finditer(t or "")}
    fixes = {}
    for t in texts:
        for m in _NAME.finditer(t or ""):
            got = f"{m.group(1)} {m.group(2)}"
            if got in known or got in fixes:
                continue
            f, l = m.group(1), m.group(2)
            for k in known:
                kf, kl = k.split()
                if (l == kl and _near(f, kf)) or (f == kf and _near(l, kl)):
                    fixes[got] = k
                    break
    return fixes


def fix_names(obj, fixes: dict[str, str]):
    """Apply name fixes to every string inside a JSON-like structure."""
    if not fixes:
        return obj
    if isinstance(obj, str):
        for wrong, right in fixes.items():
            obj = re.sub(rf"\b{re.escape(wrong)}\b", right, obj)
        return obj
    if isinstance(obj, list):
        return [fix_names(x, fixes) for x in obj]
    if isinstance(obj, dict):
        return {k: fix_names(v, fixes) for k, v in obj.items()}
    return obj
