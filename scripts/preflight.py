"""Preflight for the morning cloud run: checks everything it depends on, writes nothing, publishes nothing.
    python scripts/preflight.py
Exits non-zero if something the run can't do without is broken (Gemini, the build); audio and the database are
reported but optional, matching how the real run treats them."""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

results = []  # (name, ok, required, detail)


def check(name, required=True):
    def wrap(fn):
        t = time.time()
        try:
            detail = fn() or ""
            results.append((name, True, required, f"{detail} ({time.time() - t:.1f}s)"))
        except Exception as e:
            results.append((name, False, required, f"{type(e).__name__}: {str(e)[:160]}"))
        return fn
    return wrap


@check("Secrets present")
def _():
    missing = [k for k in ("GEMINI_API_KEY", "SUPABASE_DB_URL") if not os.environ.get(k)]
    if "GEMINI_API_KEY" in missing:
        raise RuntimeError("GEMINI_API_KEY is missing")
    return "SUPABASE_DB_URL missing: prices and quiz answers won't reach the database" if missing else "both set"


@check("Gemini: every model the morning jobs use")
def _():
    from google.genai import types
    from digest import summarize
    tasks = list(summarize._TASKS) + ["transcribe"]
    first = {t: (summarize.task_models(t) if t != "transcribe" else summarize._models(summarize.GEMINI_TRANSCRIBE_MODELS)) for t in tasks}
    models = sorted({m for chain in first.values() for m in chain})
    cfg = types.GenerateContentConfig(temperature=0, max_output_tokens=8,
                                      http_options=types.HttpOptions(timeout=60000))
    status = {}
    for m in models:
        try:
            r = summarize._with_deadline(lambda: summarize._gemini().models.generate_content(model=m, contents="Reply with: OK", config=cfg), 75)
            status[m] = "ok" if (r.text or "").strip() else "empty"
        except Exception as e:
            status[m] = str(e).split(".")[0][:40]
        print(f"  {m:28} {status[m]}", flush=True)
    dead_jobs = [t for t, chain in first.items() if not any(status.get(m) == "ok" for m in chain)]
    if dead_jobs:
        raise RuntimeError(f"no working model for: {', '.join(dead_jobs)}")
    firsts = ", ".join(f"{t}→{next(m for m in chain if status.get(m) == 'ok')}" for t, chain in first.items())
    return f"{sum(v == 'ok' for v in status.values())}/{len(models)} models answer; each job's first working model: {firsts}"


@check("Database (Supabase)", required=False)
def _():
    if not os.environ.get("SUPABASE_DB_URL"):
        raise RuntimeError("SUPABASE_DB_URL not set")
    import psycopg
    from digest import supa
    with psycopg.connect(supa._db_url(), connect_timeout=15) as c:  # same connection path as the real run
        n = c.execute("select count(*) from public.prices").fetchone()[0]
    return f"connected, {n} price rows"


@check("Voice (Kokoro audio briefing)", required=False)
def _():
    from digest import voice
    if not voice.available():
        raise RuntimeError("voice model not available: the run would skip the audio briefing")
    out = Path(tempfile.mkdtemp()) / "test.mp3"
    voice.speak("Good morning. This is a test of the Stocksplain audio briefing.", out)
    return f"spoke a test sentence ({out.stat().st_size // 1024} KB mp3)"


@check("Podcast feeds")
def _():
    import yaml
    from digest import sources
    cfg = yaml.safe_load(Path("sources.yaml").read_text())
    ok, failed = 0, []
    for src in cfg["sources"]:
        if src.get("enabled") is False:
            continue
        try:
            sources.list_source(src, 1)
            ok += 1
        except Exception:
            failed.append(src["name"])
    if not ok:
        raise RuntimeError("no podcast feed could be read")
    return f"{ok} feeds readable" + (f"; failing: {', '.join(failed)}" if failed else "")


@check("Site builds")
def _():
    from digest import build
    build.build(ROOT)
    return "built site/"


print("\nPREFLIGHT RESULTS")
for name, ok, required, detail in results:
    print(f"{'✅' if ok else ('❌' if required else '⚠️ ')} {name}: {detail}")
bad = [n for n, ok, req, _ in results if not ok and req]
print("\nREADY for the morning run." if not bad else f"\nNOT READY: {', '.join(bad)}")
sys.exit(1 if bad else 0)
