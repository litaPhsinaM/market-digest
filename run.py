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
HOT, QUIZ, AUDIO = DATA / "hot", DATA / "quiz", DATA / "audio"
STATE = DATA / "state.json"


def load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"seen": {}}


def save_state(state: dict):
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))


# Transcribe on-device on a Mac (fast, free, and we keep the transcript); elsewhere send audio to Gemini.
LOCAL_WHISPER = os.environ.get("DIGEST_TRANSCRIBE", "local" if sys.platform == "darwin" else "none") == "local"


def get_content(item) -> dict:
    """Return kwargs for summarize_item: a transcript, or raw audio for Gemini."""
    tmp = Path(tempfile.mkdtemp())
    if item.kind == "youtube":
        audio = sources.youtube_audio(item, tmp)
    else:
        audio = sources.download(item.media_url, tmp / "episode.mp3")
    if LOCAL_WHISPER or summarize.BACKEND == "ollama":
        from digest.transcribe import transcribe
        print("    transcribing…")
        return {"transcript": transcribe(audio)}
    return {"audio": audio}


def process(item, today: str) -> bool:
    print(f"  → {item.source_name}: {item.title}")
    content = get_content(item)
    if content.get("transcript"):
        (TRANSCRIPTS / f"{item.id}.txt").write_text(content["transcript"])
    summary = summarize.summarize_item(item, **content)
    record = {**item.to_dict(), "digest_date": today, "backend": summarize.BACKEND,
              "model": summarize.OLLAMA_MODEL if summarize.BACKEND == "ollama" else summarize.GEMINI_MODEL,
              "summary": summary.model_dump()}
    (ITEMS / f"{item.id}.json").write_text(json.dumps(record, indent=1))
    print(f"    {'✓' if summary.worth_reading else '✗ not worth reading:'} {summary.headline}")
    return True


def write_brief(today: str):
    todays = [json.loads(p.read_text()) for p in ITEMS.glob("*.json")]
    todays = [r for r in todays if r["digest_date"] == today and r["summary"]["worth_reading"]]
    if not todays:
        return
    print(f"Writing daily brief from {len(todays)} items")
    brief = summarize.daily_brief(todays)
    (BRIEFS / f"{today}.json").write_text(json.dumps({"date": today, **brief.model_dump()}, indent=1))


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
    headlines = news.collect(cfg.get("news", []))
    print(f"Picking hot topics from {len(headlines)} headlines")
    if not headlines:
        return
    topics = summarize.hot_topics(headlines[:150])
    used = {i for t in topics.topics for i in t.headline_ids}
    (HOT / f"{today}.json").write_text(json.dumps({
        "date": today, "topics": topics.model_dump()["topics"],
        "headlines": {h["id"]: h for h in headlines if h["id"] in used},
        "latest": headlines[:12], "feeds": len(cfg.get("news", [])), "scanned": len(headlines),
    }, indent=1))


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
    kept = []
    for c in snap["companies"]:
        if c["symbol"] not in watchlist and not market.name_matches(c["name"], context.get(c["symbol"], "")):
            print(f"  dropped {c['symbol']} ({c['name']}): not the company the story is about")
            continue
        c["mentioned_in"] = mentioned.get(c["symbol"], [])
        kept.append(c)
    snap["companies"] = kept
    (MARKET / f"{today}.json").write_text(json.dumps(snap, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--market-only", action="store_true", help="refresh today's market snapshot, then build")
    ap.add_argument("--hot-only", action="store_true", help="refresh today's hot topics and market snapshot, then build")
    ap.add_argument("--extras-only", action="store_true", help="regenerate today's quiz and audio briefing, then build")
    ap.add_argument("--redo", nargs="*", metavar="ID",
                    help="re-summarize saved items from their transcripts (all of today's if no ids), redo the brief, build")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=2, help="max new items per source")
    args = ap.parse_args()

    for d in (ITEMS, BRIEFS, TRANSCRIPTS, MARKET, HOT, QUIZ, AUDIO):
        d.mkdir(parents=True, exist_ok=True)
    if args.build_only:
        build.build(ROOT)
        return

    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    state = load_state()
    today = dt.date.today().isoformat()
    if args.market_only or args.hot_only:
        if args.hot_only:
            write_hot(today, cfg)
        write_market(today, cfg)
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
    try:
        write_extras(today)
    except Exception as e:
        print(f"! quiz/audio failed: {e}")
    build.build(ROOT)


if __name__ == "__main__":
    main()
