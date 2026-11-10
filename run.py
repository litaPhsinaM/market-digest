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
import sys
import tempfile
import traceback
from pathlib import Path

import yaml

from digest import build, sources, summarize

ROOT = Path(__file__).parent
DATA = ROOT / "data"
ITEMS, BRIEFS, TRANSCRIPTS, MARKET = DATA / "items", DATA / "briefs", DATA / "transcripts", DATA / "market"
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


def write_market(today: str, cfg: dict):
    from digest import market
    todays = [r for r in (json.loads(p.read_text()) for p in ITEMS.glob("*.json")) if r["digest_date"] == today]
    mentioned = market.tickers_from_summaries(todays)
    tickers = list(dict.fromkeys(list(mentioned) + cfg.get("watchlist", [])))
    print(f"Fetching market snapshot for {len(tickers)} companies")
    snap = market.snapshot(tickers)
    for c in snap["companies"]:
        c["mentioned_in"] = mentioned.get(c["symbol"], [])
    (MARKET / f"{today}.json").write_text(json.dumps(snap, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--market-only", action="store_true", help="refresh today's market snapshot, then build")
    ap.add_argument("--redo", nargs="*", metavar="ID",
                    help="re-summarize saved items from their transcripts (all of today's if no ids), redo the brief, build")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=2, help="max new items per source")
    args = ap.parse_args()

    for d in (ITEMS, BRIEFS, TRANSCRIPTS, MARKET):
        d.mkdir(parents=True, exist_ok=True)
    if args.build_only:
        build.build(ROOT)
        return

    cfg = yaml.safe_load((ROOT / "sources.yaml").read_text())
    state = load_state()
    today = dt.date.today().isoformat()
    if args.market_only:
        write_market(today, cfg)
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
        write_market(today, cfg)
    except Exception as e:  # prices are a nice-to-have; never block the digest
        print(f"! market snapshot failed: {e}")
    build.build(ROOT)


if __name__ == "__main__":
    main()
