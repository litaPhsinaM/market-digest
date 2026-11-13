"""Daily run: find new episodes/videos, summarize them, write today's brief, build the site.

  python run.py                 # full run
  python run.py --dry-run       # just list what's new
  python run.py --build-only    # rebuild the site from saved summaries
  python run.py --source indicator --limit 1
Backend is chosen with DIGEST_BACKEND=gemini|ollama (see digest/summarize.py).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

import yaml

from digest import build, sources, summarize

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ITEMS, BRIEFS, TRANSCRIPTS, MARKET = DATA / "items", DATA / "briefs", DATA / "transcripts", DATA / "market"
HOT, QUIZ, AUDIO, ECON = DATA / "hot", DATA / "quiz", DATA / "audio", DATA / "econ"
STATE = DATA / "state.json"


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"seen": {}}


def save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))


# How episodes get a transcript (the quality checks and forecast quotes are verified against it):
#   local  = Whisper on the Mac (default on macOS)   gemini = Gemini transcribes the audio (default elsewhere, e.g. CI)
#   none   = no transcript; Gemini summarizes the audio directly (no checks, no forecasts)
TRANSCRIBE = os.environ.get("DIGEST_TRANSCRIBE", "local" if sys.platform == "darwin" else "gemini")


def get_content(item) -> dict:
    """Return kwargs for summarize_item: a transcript, or raw audio for Gemini."""
    tmp = Path(tempfile.mkdtemp())
    if item.kind == "youtube":
        audio = sources.youtube_audio(item, tmp)
    else:
        audio = sources.download(item.media_url, tmp / "episode.mp3")
    if TRANSCRIBE == "local" or summarize.BACKEND == "ollama":
        from digest.transcribe import transcribe
        print("    transcribing…")
        return {"transcript": transcribe(audio)}
    if TRANSCRIBE == "gemini":
        print("    transcribing (Gemini)…")
        if text := summarize.transcribe(item, audio):
            return {"transcript": text}
        print("    summarizing the audio directly instead (no transcript checks or forecasts for this one)")
    return {"audio": audio}


def process(item, today: str) -> bool:
    print(f"  → {item.source_name}: {item.title}")
    content = get_content(item)
    if content.get("transcript"):
        (TRANSCRIPTS / f"{item.id}.txt").write_text(content["transcript"])
    summary = summarize.summarize_item(item, **content)
    record = {**item.to_dict(), "digest_date": today, "backend": summarize.BACKEND,
              "model": summarize.OLLAMA_MODEL if summarize.BACKEND == "ollama" else (summarize.last_model or summarize.GEMINI_MODEL),
              "summary": summary.model_dump()}
    (ITEMS / f"{item.id}.json").write_text(json.dumps(record, indent=1))
    print(f"    {'✓' if summary.worth_reading else '✗ not worth reading:'} {summary.headline}")
    if content.get("transcript") and summary.worth_reading:
        log_claims(item, content["transcript"])
    return True


def write_brief(today: str):
    todays = [json.loads(p.read_text()) for p in ITEMS.glob("*.json")]
    todays = [r for r in todays if r["digest_date"] == today and r["summary"]["worth_reading"]]
    if not todays:
        return
    print(f"Writing daily brief from {len(todays)} items")
    brief = summarize.daily_brief(todays)
    (BRIEFS / f"{today}.json").write_text(json.dumps({"date": today, **brief.model_dump()}, indent=1))


def log_claims(item, transcript: str):
    from digest import claims
    try:
        claims.add(claims.extract(item, transcript))
    except Exception as e:
        print(f"    ! forecast extraction failed: {e}")


def backfill_claims():
    from digest import claims
    have = {c["item_id"] for c in claims.load()}
    for p in sorted(ITEMS.glob("*.json")):
        r = json.loads(p.read_text())
        t = TRANSCRIPTS / f"{r['id']}.txt"
        if r["id"] in have or not t.exists() or not r["summary"]["worth_reading"]:
            continue
        print(f"  🎙 {r['source_name']}: {r['title']}")
        log_claims(sources.Item(**{k: r[k] for k in sources.Item.__dataclass_fields__}), t.read_text())


def redo(ids: list[str], today: str):
    records = [json.loads(p.read_text()) for p in ITEMS.glob("*.json")]
    records = [r for r in records if (r["id"] in ids if ids else r["digest_date"] == today)]
    for r in records:
        tpath = TRANSCRIPTS / f"{r['id']}.txt"
        if not tpath.exists():
            print(f"! {r['id']}: no saved transcript, skipping")
            continue
        item = sources.Item(**{k: r[k] for k in sources.Item.__dataclass_fields__})
        print(f"  ↻ {item.source_name}: {item.title}")
        r["summary"] = summarize.summarize_item(item, transcript=tpath.read_text()).model_dump()
        (ITEMS / f"{item.id}.json").write_text(json.dumps(r, indent=1))
    for date in sorted({r["digest_date"] for r in records}):
        write_brief(date)
    build.build(ROOT)


def write_hot(today: str, cfg: dict):
    from digest import news
    scanned = news.collect(cfg.get("news", []))
    headlines = news.balanced(scanned)
    print(f"Picking hot topics from {len(headlines)} headlines")
    if not headlines:
        return
    topics = summarize.hot_topics(headlines)
    used = {i for t in topics.topics for i in t.headline_ids}
    (HOT / f"{today}.json").write_text(json.dumps({
        "date": today, "topics": topics.model_dump()["topics"],
        "headlines": {h["id"]: h for h in headlines if h["id"] in used},
        "latest": scanned[:12], "feeds": len(cfg.get("news", [])), "scanned": len(scanned),
    }, indent=1))
    fix_spellings(today, [h["title"] + " " + h["blurb"] for h in scanned])


def fix_spellings(today: str, reference: list[str]):
    """Correct names the audio transcription misspelled, using how today's newsroom headlines spell them."""
    from digest import checks
    files = [p for p in ITEMS.glob("*.json") if json.loads(p.read_text()).get("digest_date") == today]
    if (BRIEFS / f"{today}.json").exists():
        files.append(BRIEFS / f"{today}.json")
    from digest import claims as _claims
    ledger = _claims.load()
    fx = checks.name_fixes([c["claim"] for c in ledger if c.get("said_on") == today], reference)
    if fx:
        for c in ledger:
            if c.get("said_on") == today:
                c["claim"], c["subject"] = checks.fix_names(c["claim"], fx), checks.fix_names(c.get("subject", ""), fx)
        _claims.save(ledger)
        print("  spelling (forecasts): " + ", ".join(f"{a} → {b}" for a, b in fx.items()))
    for p in files:
        rec = json.loads(p.read_text())
        part = rec["summary"] if "summary" in rec else rec
        fixes = checks.name_fixes(re.findall(r'"([^"]{3,})"', json.dumps(part)), reference)
        if fixes:
            fixed = checks.fix_names(rec, fixes)
            p.write_text(json.dumps(fixed, indent=1))
            print(f"  spelling: {p.stem}: " + ", ".join(f"{a} → {b}" for a, b in fixes.items()))


def write_extras(today: str):
    """Daily quiz + spoken briefing, built from today's stories and hot topics."""
    items = [r for r in (json.loads(p.read_text()) for p in ITEMS.glob("*.json"))
             if r["digest_date"] == today and r["summary"]["worth_reading"]]
    hot_p, brief_p = HOT / f"{today}.json", BRIEFS / f"{today}.json"
    hot = json.loads(hot_p.read_text()) if hot_p.exists() else None
    brief = json.loads(brief_p.read_text()) if brief_p.exists() else None
    if not items and not hot:
        return
    print("Writing quiz")
    q = summarize.quiz(items, hot)
    (QUIZ / f"{today}.json").write_text(json.dumps({"date": today, **q.model_dump()}, indent=1))
    from digest import supa
    if supa.available():
        try:
            supa.push_quiz_keys(today, q.model_dump())
        except Exception as e:
            print(f"! pushing quiz answers to Supabase failed: {e}")

    from digest import voice
    if not voice.available():
        print("  (no .venv-tts, skipping audio briefing)")
        return
    print("Writing audio briefing")
    words = dt.date.fromisoformat(today).strftime("%A, %B %-d")
    b = summarize.briefing(items, hot, brief, words)
    voice.speak(b.script, AUDIO / f"{today}.mp3")
    (AUDIO / f"{today}.json").write_text(json.dumps({"date": today, "script": b.script}, indent=1))
    voice.prune(AUDIO)


def write_econ(today: str):
    """Official US economic numbers + upcoming data releases (FRED). Optional: skipped without FRED_API_KEY."""
    from digest import econ
    try:
        snap = econ.snapshot(today)
    except Exception as e:
        print(f"! economy card failed: {e}")
        return
    if snap:
        ECON.mkdir(parents=True, exist_ok=True)
        (ECON / f"{today}.json").write_text(json.dumps(snap, indent=1))
        print(f"Economy card: {len(snap['indicators'])} numbers, {len(snap['upcoming'])} upcoming releases")


def write_market(today: str, cfg: dict):
    from digest import market
    todays = [r for r in (json.loads(p.read_text()) for p in ITEMS.glob("*.json")) if r["digest_date"] == today]
    mentioned = market.tickers_from_summaries(todays)
    # Text each ticker was mentioned in, so we can check the ticker really is the company being discussed.
    context = {sym: " ".join(json.dumps(r["summary"]) for r in todays if r["id"] in ids) for sym, ids in mentioned.items()}
    hot = HOT / f"{today}.json"
    if hot.exists():
        for t in json.loads(hot.read_text())["topics"]:
            for sym in t["tickers"]:
                sym = sym.strip().upper()
                if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", sym):
                    mentioned.setdefault(sym, [])
                    context[sym] = context.get(sym, "") + f" {t['title']} {t['explanation']}"
    watchlist = cfg.get("watchlist", [])
    tickers = list(dict.fromkeys(list(mentioned) + watchlist))
    print(f"Fetching market snapshot for {len(tickers)} companies")
    snap = market.snapshot(tickers)
    # Yahoo sometimes rate-limits or fails wholesale without raising: don't replace a good snapshot with an empty one.
    if not snap["indices"] or len(snap["universe"]) < len(market.UNIVERSE) // 2:
        raise RuntimeError(f"Yahoo returned too little ({len(snap['indices'])} indices, {len(snap['universe'])} of "
                           f"{len(market.UNIVERSE)} stocks); keeping the last snapshot")
    kept = []
    for c in snap["companies"]:
        if c["symbol"] not in watchlist and not market.name_matches(c["name"], context.get(c["symbol"], "")):
            print(f"  dropped {c['symbol']} ({c['name']}): not the company the story is about")
            continue
        c["mentioned_in"] = mentioned.get(c["symbol"], [])
        kept.append(c)
    snap["companies"] = kept
    (MARKET / f"{today}.json").write_text(json.dumps(snap, indent=1))
    from digest import supa
    if supa.available():
        try:
            supa.push_prices(snap)
        except Exception as e:
            print(f"! pushing prices to Supabase failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--market-only", action="store_true", help="refresh today's market snapshot, then build")
    ap.add_argument("--hot-only", action="store_true", help="refresh today's hot topics and market snapshot, then build")
    ap.add_argument("--extras-only", action="store_true", help="regenerate today's quiz and audio briefing, then build")
    ap.add_argument("--claims", action="store_true", help="log forecasts for saved episodes that don't have them yet, score due ones, build")
    ap.add_argument("--redo", nargs="*", metavar="ID",
                    help="re-summarize saved items from their transcripts (all of today's if no ids), redo the brief, build")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=2, help="max new items per source")
    ap.add_argument("--max-minutes", type=float, help="stop starting new episodes after this long (the rest wait for "
                                                      "the next run), so a time-limited cloud job still finishes the day")
    args = ap.parse_args()
    started = dt.datetime.now()

    for d in (ITEMS, BRIEFS, TRANSCRIPTS, MARKET, HOT, QUIZ, AUDIO, ECON):
        d.mkdir(parents=True, exist_ok=True)
    if args.build_only:
        build.build(ROOT)
        return

    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    state = load_state()
    today = dt.date.today().isoformat()
    if args.market_only or args.hot_only:
        # Market data is filed by the New York date (the cloud job runs in UTC, which is tomorrow by evening ET).
        if args.market_only:
            from digest import hours
            today = dt.datetime.now(hours.NY).date().isoformat()
        if args.hot_only:
            write_hot(today, cfg)
        write_market(today, cfg)
        write_econ(today)
        build.build(ROOT)
        return
    if args.claims:
        from digest import claims
        backfill_claims()
        claims.resolve()
        build.build(ROOT)
        return
    if args.extras_only:
        write_extras(today)
        build.build(ROOT)
        return
    if args.redo is not None:
        redo(args.redo, today)
        return
    new_count = 0

    for src in cfg["sources"]:
        if args.source and src["id"] != args.source or src.get("enabled") is False:
            continue
        try:
            found = sources.list_source(src, args.limit)
        except Exception as e:
            print(f"! {src['name']}: listing failed: {e}")
            continue
        first_time = not any(k.startswith(src["id"] + "-") for k in state["seen"])
        new = [i for i in found if i.id not in state["seen"]]
        if first_time:  # don't backfill a whole channel; start from its latest item
            for i in new[1:]:
                state["seen"][i.id] = "backlog"
            new = new[:1]
        print(f"{src['name']}: {len(new)} new")
        for item in new:
            if args.dry_run:
                print(f"  · {item.title} ({(item.duration or 0) // 60} min)")
                continue
            if args.max_minutes and (dt.datetime.now() - started).total_seconds() > args.max_minutes * 60:
                print(f"    (out of time, leaving for the next run: {item.title})")
                continue
            try:
                process(item, today)
                state["seen"][item.id] = "done"
                new_count += 1
            except Exception as e:
                print(f"    ! failed (will retry next run): {e}")
                traceback.print_exc(limit=2)
            save_state(state)

    if args.dry_run:
        return
    if new_count:
        write_brief(today)
    try:
        write_hot(today, cfg)
    except Exception as e:
        print(f"! hot topics failed: {e}")
    try:
        write_market(today, cfg)
    except Exception as e:  # prices are a nice-to-have; never block the digest
        print(f"! market snapshot failed: {e}")
    write_econ(today)
    try:
        write_extras(today)
    except Exception as e:
        print(f"! quiz/audio failed: {e}")
    try:
        from digest import claims
        claims.resolve()
    except Exception as e:
        print(f"! scoring forecasts failed: {e}")
    build.build(ROOT)


if __name__ == "__main__":
    main()
