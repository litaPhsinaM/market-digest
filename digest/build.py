"""Render saved summaries into a static site in ./site."""
import datetime as dt
import json
import re
import shutil
import os
from collections import defaultdict
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape


def _minutes(secs):
    return round((secs or 0) / 60)


def _num(v, digits=2):
    return "—" if v is None else f"{v:,.{digits}f}"


def _big(v):
    if v is None:
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(v) >= div:
            return f"{v / div:.2f}{suf}"
    return f"{v:,.0f}"


def _initials(name):
    words = [w for w in name.split() if w[0].isalpha() and w.lower() not in ("the", "from", "of", "and")]
    return "".join(w[0].upper() for w in words[:2])


def _quote_fmt(q):
    """Display strings for a quote. Yields are shown in % with basis-point moves, like on a trading desk."""
    if q["symbol"] == "^TNX":
        bp = q["change"] * 100
        return {"price": f"{q['price']:.2f}%", "change": f"{'+' if bp >= 0 else '−'}{abs(bp):.0f} bp"}
    prefix = "$" if q["symbol"] == "BTC-USD" or not q["symbol"].startswith("^") else ""
    digits = 0 if q["symbol"] == "BTC-USD" else 2
    pct = q["change_pct"]
    return {"price": f"{prefix}{q['price']:,.{digits}f}", "change": f"{'+' if pct >= 0 else '−'}{abs(pct):.2f}%"}


def _search_index(items, hots, glossary, markets):
    """Everything searchable from the ⌘K palette: stories, hot topics, glossary terms, companies."""
    idx = []
    for it in items:
        if it["summary"]["worth_reading"]:
            idx.append({"k": "Story", "t": it["summary"]["headline"], "s": it["summary"]["tldr"], "m": it["source_name"],
                        "d": it["digest_date"], "u": f"days/{it['digest_date']}.html#{it['id']}"})
    for date, hot in hots.items():
        for t in hot["topics"]:
            idx.append({"k": "Hot", "t": t["title"], "s": t["explanation"], "m": "What's hot", "d": date, "u": f"days/{date}.html#hot-h"})
    for t in glossary:
        idx.append({"k": "Term", "t": t["term"], "s": t["definition"], "m": "Glossary", "u": "glossary.html#" + _slug(t["term"])})
    if markets:
        latest = markets[max(markets)]
        for c in latest["companies"]:
            idx.append({"k": "Company", "t": f"{c['name']} ({c['symbol']})", "s": c.get("sector") or "", "m": c["symbol"],
                        "u": f"index.html#co-{c['symbol']}"})
    return idx


def _bold(text):
    """Course text may use **bold**; everything else is escaped."""
    from markupsafe import Markup, escape
    return Markup(re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", str(escape(text))))


def _scorecard(data):
    path = data / "claims.json"
    ledger = json.loads(path.read_text()) if path.exists() else []
    scored = [c for c in ledger if c["status"] in ("right", "wrong")]
    acc = lambda cs: round(100 * sum(c["status"] == "right" for c in cs) / len(cs)) if cs else None
    people = defaultdict(list)
    for c in scored:
        people[c["speaker"]].append(c)
    speakers = sorted(({"speaker": k, "role": v[-1]["role"], "scored": len(v), "right": sum(c["status"] == "right" for c in v), "accuracy": acc(v)}
                       for k, v in people.items() if len(v) >= 3), key=lambda s: (-s["accuracy"], -s["scored"]))
    shows = defaultdict(list)
    for c in ledger:
        shows[c["source"]].append(c)
    show_rows = sorted(({"source": k, "total": len(v), "scored": sum(c["status"] in ("right", "wrong") for c in v),
                         "accuracy": acc([c for c in v if c["status"] in ("right", "wrong")])} for k, v in shows.items()), key=lambda s: -s["total"])
    return {"stats": {"total": len(ledger), "open": sum(c["status"] == "open" for c in ledger), "scored": len(scored), "accuracy": acc(scored)},
            "since": min((c["said_on"] for c in ledger), default=None), "speakers": speakers, "shows": show_rows,
            "open": sorted((c for c in ledger if c["status"] in ("open", "awaiting_check")), key=lambda c: c["deadline"]),
            "resolved": sorted(scored, key=lambda c: c.get("resolved_on", ""), reverse=True)[:50]}


def _slug(text):
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")



# ---------- "Today in 60 seconds": one slide per different story ----------
# Every podcast leads with the day's biggest story, so slides are de-duplicated: a slide is skipped when it shares a
# company/ticker or a name with one already shown, and an episode whose lead repeats falls back to its next key
# point about something else.
_STOP = set("""The This That These What Why How When Where Who CEO CFO AI US UK EU Inc Corp Co Wall Street Stocks Stock
Market Markets Global New Big Today Week Year America American Americans World Says Said After Amid Over From With And
For Into Its Their Our Your Not More Less First Last Top Q1 Q2 Q3 Q4 January February March April May June July August
September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday""".split())


def _keys(text: str, tickers=()) -> set[str]:
    text = re.sub(r"[’']s\b", "", text or "")
    words = {w for w in re.findall(r"\b[A-Z][A-Za-z]{2,}\b", text) if w not in _STOP}
    tks = set()
    for t in tickers or ():
        m = re.search(r"\(([A-Z.]{1,6})\)", t)
        tks.add(m.group(1) if m else t.split()[0])
        name = re.sub(r"\s*\(.*", "", t).split()
        if name and name[0][0].isupper() and not name[0].isupper():
            tks.add(name[0])
    return {k.lower() for k in words | tks}


def _named(tickers, text: str) -> list[str]:
    """Only the tickers whose company is actually named in this text (an episode's ticker list covers all of it)."""
    out = []
    for t in tickers or ():
        name = re.sub(r"\s*\(.*", "", t).split()
        sym = re.search(r"\(([A-Z.]{1,6})\)", t)
        if (name and name[0] in text) or (sym and sym.group(1) in text) or (t.isupper() and re.search(rf"\b{t}\b", text)):
            out.append(t)
    return out


def story_slides(hot: dict | None, items: list[dict], max_hot: int = 8, max_total: int = 14) -> list[dict]:
    used: set[str] = set()
    out = []
    for t in (hot or {}).get("topics", [])[:max_hot]:
        k = _keys(t["title"] + " " + t["why_it_matters"], _named(t.get("tickers"), t["title"]))
        if k & used:
            continue
        used |= k
        out.append({"kind": "hot", "label": "What’s hot · " + str(len(out) + 1), "title": t["title"],
                    "text": t["explanation"], "why": t["why_it_matters"]})
    for it in items:
        s = it["summary"]
        cands = [(s["headline"], s["tldr"], {"lesson": s["lesson"]}, _keys(s["headline"], _named(s.get("tickers"), s["headline"])))]
        for kp in s.get("key_points", []):
            both = kp["point"] + " " + kp["why_it_matters"]
            cands.append((kp["point"], kp["why_it_matters"], {}, _keys(both, _named(s.get("tickers"), both))))
        for title, text, extra, k in cands:
            if not (k & used):
                used |= k
                out.append({"kind": "story", "label": it["source_name"], "title": title, "text": text,
                            "href": "#" + it["id"], **extra})
                break
        if len(out) >= max_total:
            break
    return out



def _arch_stats(root: Path, data: Path, items: list, hots: dict) -> dict:
    """Real numbers for the engineering page, counted from the code and data at build time."""
    import glob as _glob
    lines = lambda pats: sum(sum(1 for _ in open(f, encoding="utf-8", errors="ignore")) for p in pats for f in _glob.glob(str(root / p)))
    sql = "".join(Path(f).read_text() for f in sorted(_glob.glob(str(root / "supabase/migrations/*.sql"))))
    tables = sorted(set(re.findall(r"create table if not exists public\.(\w+)", sql)))
    summ = (root / "digest/summarize.py").read_text()
    tasks = re.search(r"_TASKS = \{(.*?)\n\}", summ, re.S)
    routing = [{"job": k.replace("_", " "), "models": [m.replace("gemini-", "") for m in v.split(",")]}
               for k, v in re.findall(r'"(\w+)":\s*"([^"]+)"', tasks.group(1))] if tasks else []
    tests = sum(len(re.findall(r"^def test_", Path(f).read_text(), re.M)) for f in _glob.glob(str(root / "tests/*.py")))
    per_day = {}
    for it in items:
        per_day[it["digest_date"]] = per_day.get(it["digest_date"], 0) + 1
    days = sorted(set(per_day) | set(hots))[-14:]
    series = [{"date": d, "episodes": per_day.get(d, 0), "headlines": (hots.get(d) or {}).get("scanned", 0)} for d in days]
    return {
        "loc": [{"lang": "Python", "n": lines(["digest/*.py", "run.py", "migrate.py", "scripts/*.py"]), "c": "#3fbf8f"},
                {"lang": "JavaScript", "n": lines(["templates/*.js"]), "c": "#e0a33b"},
                {"lang": "SQL", "n": lines(["supabase/migrations/*.sql"]), "c": "#6aa0ff"},
                {"lang": "HTML templates", "n": lines(["templates/*.html"]), "c": "#ef7d7d"},
                {"lang": "CSS", "n": lines(["templates/*.css"]), "c": "#b48cff"}],
        "tables": tables, "n_functions": len(re.findall(r"create or replace function", sql)),
        "n_policies": len(re.findall(r"create policy", sql)), "n_migrations": len(_glob.glob(str(root / "supabase/migrations/*.sql"))),
        "n_tests": tests, "routing": routing, "series": series,
        "max_ep": max([d["episodes"] for d in series] or [1]) or 1, "max_hl": max([d["headlines"] for d in series] or [1]) or 1,
    }


def build(root: Path):
    # Build into a temporary folder and swap it in at the end, so the live site is never half-built,
    # and a failed build leaves the previous site untouched.
    data, final, out = root / "data", root / "site", root / "site.tmp"
    items = [json.loads(p.read_text()) for p in sorted((data / "items").glob("*.json"))]
    briefs = {p.stem: json.loads(p.read_text()) for p in (data / "briefs").glob("*.json")}
    cfg = yaml.safe_load((root / "sources.yaml").read_text())
    srcs, feeds = cfg["sources"], cfg.get("news", [])
    load = lambda sub: {p.stem: json.loads(p.read_text()) for p in (data / sub).glob("*.json")} if (data / sub).exists() else {}
    hots, quizzes, audio, econs = load("hot"), load("quiz"), load("audio"), load("econ")

    days = defaultdict(list)
    for it in items:
        days[it["digest_date"]].append(it)
    dates = sorted(set(days) | set(hots), reverse=True)

    glossary = {}
    for it in sorted(items, key=lambda i: i["digest_date"]):
        for t in it["summary"]["glossary"]:
            key = t["term"].strip().lower()
            entry = glossary.setdefault(key, {**t, "seen": []})
            entry["seen"].append({"date": it["digest_date"], "id": it["id"], "title": it["summary"]["headline"]})
    course_path = data / "learn" / "course.json"
    if course_path.exists():
        for u in json.loads(course_path.read_text())["units"]:
            for l in u["lessons"]:
                for t in l.get("key_terms", []):
                    entry = glossary.setdefault(t["term"].strip().lower(), {"term": t["term"], "definition": t["definition"], "example": "", "seen": []})
                    entry.setdefault("lessons", []).append({"id": l["id"], "title": l["title"]})
    # dictionary: merge duplicate spellings into one entry, give every word a topic (data/glossary_meta.json)
    from digest import glossary_meta
    meta = glossary_meta.load()
    for key in list(glossary):
        target = meta.get(key, {}).get("same_as")
        if target and target in glossary and target != key:
            main, dup = glossary[target], glossary.pop(key)
            main["seen"] = main.get("seen", []) + dup.get("seen", [])
            main["lessons"] = main.get("lessons", []) + [l for l in dup.get("lessons", []) if l not in main.get("lessons", [])]
            main.setdefault("aka", []).append(dup["term"])
            if dup.get("lessons") and not main.get("lessons_def"):  # a lesson's definition is the reviewed one: prefer it
                main["definition"], main["lessons_def"] = dup["definition"], True
    topics = {k: (label, emoji) for k, label, emoji, _ in glossary_meta.TOPICS}
    for key, t in glossary.items():
        t["topic"] = meta.get(key, {}).get("topic", "other")
        t["topic_label"], t["topic_emoji"] = topics.get(t["topic"], topics["other"])
        first = t["term"].strip()[:1].upper()
        t["letter"] = first if first.isalpha() else "#"
        t["seen"] = sorted({s["id"]: s for s in t.get("seen", [])}.values(), key=lambda s: s["date"], reverse=True)
    glossary = sorted(glossary.values(), key=lambda t: t["term"].lower().lstrip("'\"("))
    finance = [t for t in glossary if t["topic"] != "other" and len(t["definition"]) > 40]
    word_of_day = finance[dt.date.today().toordinal() % len(finance)] if finance else None
    glossary_topics = [{"key": k, "label": label, "emoji": e, "n": sum(t["topic"] == k for t in glossary)}
                       for k, label, e, _ in glossary_meta.TOPICS if any(t["topic"] == k for t in glossary)]

    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    env.filters["minutes"] = _minutes
    env.filters["num"] = _num
    env.filters["big"] = _big
    env.filters["qf"] = _quote_fmt
    env.filters["initials"] = _initials
    env.filters["slug"] = _slug
    env.filters["bold"] = _bold
    env.globals["supabase"] = cfg.get("supabase") or {"url": "", "key": ""}
    markets = {p.stem: json.loads(p.read_text()) for p in (data / "market").glob("*.json")}
    src_index = {s["id"]: n for n, s in enumerate(srcs)}

    if out.exists():
        shutil.rmtree(out)
    (out / "days").mkdir(parents=True)
    for asset in ("style.css", "app.js", "features.js", "account.js", "social.js", "learn.js", "admin.js", "quant.js", "supabase.js", "manifest.webmanifest"):
        shutil.copy(root / "templates" / asset, out / asset)
    shutil.copytree(root / "templates" / "icons", out / "icons")
    version = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    (out / "sw.js").write_text((root / "templates" / "sw.js").read_text().replace("__VERSION__", version))
    (out / "audio").mkdir()
    for date in audio:
        mp3 = data / "audio" / f"{date}.mp3"
        if mp3.exists():
            shutil.copy(mp3, out / "audio" / mp3.name)

    def day_ctx(date):
        its = sorted(days[date], key=lambda i: (not i["summary"]["worth_reading"], i["source_name"]))
        # Prices: the newest snapshot on or after this day (the home page gets intraday updates filed under a later
        # date, e.g. by the cloud job running on UTC), falling back to the last one before it for older days.
        later = sorted(d for d in markets if d >= date)
        mkt = markets[later[-1]] if later and date == dates[0] else markets.get(date) or (markets[later[0]] if later else None)
        hot = hots.get(date)
        if hot:  # one link per outlet, so "Bloomberg ×3" reads as three different newsrooms
            for t in hot["topics"]:
                by_src = {}
                for i in t["headline_ids"]:
                    h = hot["headlines"].get(i)
                    if h:
                        by_src.setdefault(h["source"], h)
                t["links"] = list(by_src.values())[:4]
        if mkt:
            for c in mkt["companies"]:
                if c.get("next_earnings") and c["next_earnings"] < date:
                    c["next_earnings"] = None
        soon = (dt.date.fromisoformat(date) + dt.timedelta(days=14)).isoformat()
        earnings = sorted((c for c in (mkt or {}).get("companies", []) if c.get("next_earnings") and c["next_earnings"] <= soon),
                          key=lambda c: c["next_earnings"])
        cos = (mkt or {}).get("companies", [])
        pool = [c for c in cos if c.get("mentioned_in")] or cos
        call_co = pool[dt.date.fromisoformat(date).toordinal() % len(pool)] if pool else None
        good = [i for i in its if i["summary"]["worth_reading"]]
        econ_day = max((d for d in econs if d <= date), default=None)
        seen_keys, repeats = set(), set()
        for it in good:  # the first episode on a story stays up front; later ones on the same story fold away
            lead = re.split(r"[;:]", it["summary"]["headline"])[0]  # the episode's main story, not its second item
            k = _keys(lead, _named(it["summary"].get("tickers"), lead))
            if k and k & seen_keys:
                repeats.add(it["id"])
            seen_keys |= k
        return {"date": date, "brief": briefs.get(date), "items": its, "story_slides": story_slides(hots.get(date), good),
                "repeat_ids": repeats,
                "econ": econs.get(econ_day) if econ_day else None, "market": mkt, "hot": hots.get(date), "call_co": call_co,
                "quiz": quizzes.get(date), "earnings": earnings,
                "audio": audio.get(date) if (out / "audio" / f"{date}.mp3").exists() else None,
                "n_podcasts": len(srcs), "n_feeds": len(feeds),
                "by_id": {i["id"]: i for i in its}, "src_index": src_index,
                "pretty_date": dt.date.fromisoformat(date).strftime("%A, %B %-d, %Y"),
                "listen_min": sum(_minutes(i["duration"]) for i in its)}

    today_iso = dt.date.today().isoformat()
    site_url = os.environ.get("SITE_URL", "https://stocksplain.app/")
    pages = []  # (path, lastmod) for sitemap.xml

    def render(name, path, prefix, lastmod=None, **ctx):
        canonical = site_url + ("" if path == "index.html" else path)
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_text(env.get_template(name).render(prefix=prefix, canonical=canonical, site_url=site_url, **ctx))
        if name not in ("admin.html", "empty.html"):
            pages.append((canonical, lastmod or today_iso))

    for i, date in enumerate(dates):
        nav = {"newer": dates[i - 1] if i else None, "older": dates[i + 1] if i + 1 < len(dates) else None}
        render("day.html", f"days/{date}.html", "../", lastmod=date, **day_ctx(date), nav=nav)
    if dates:
        render("day.html", "index.html", "", lastmod=dates[0], **day_ctx(dates[0]),
               nav={"newer": None, "older": dates[1] if len(dates) > 1 else None}, is_home=True)
    else:
        render("empty.html", "index.html", "")
    render("archive.html", "archive.html", "",
           days=[{"date": d, **day_ctx(d)} for d in dates])
    render("glossary.html", "glossary.html", "", terms=glossary, topics=glossary_topics, word_of_day=word_of_day,
           letters=sorted({t["letter"] for t in glossary}))
    claims_ledger = json.loads((data / "claims.json").read_text()) if (data / "claims.json").exists() else []
    show_stats = {}
    for src in srcs:
        mine = [i for i in items if i["source_id"] == src["id"] and i["summary"]["worth_reading"]]
        latest = max(mine, key=lambda i: (i["digest_date"], i.get("published", "")), default=None)
        show_stats[src["id"]] = {"episodes": len(mine), "forecasts": sum(c["source"] == src["name"] for c in claims_ledger),
                                 "latest": {"title": latest["summary"]["headline"], "date": latest["digest_date"], "id": latest["id"]} if latest else None}
    latest_hot = hots.get(dates[0]) if dates else None
    used_today = {}
    if latest_hot:
        for t in latest_hot.get("topics", []):
            for hid in t.get("headline_ids", []):
                h = latest_hot.get("headlines", {}).get(hid)
                if h:
                    used_today[h["source"]] = used_today.get(h["source"], 0) + 1
    beats = [("markets", "Markets & companies", "📈"), ("economy", "Economy & the Fed", "🏛"), ("tech", "Technology", "🤖"),
             ("energy", "Energy & resources", "⚡"), ("policy", "Policy & politics", "🧾"), ("world", "World business", "🌍")]
    feed_groups = [{"key": k, "label": label, "emoji": e, "feeds": [f for f in feeds if f.get("beat", "markets") == k]} for k, label, e in beats]
    render("sources.html", "sources.html", "", sources=srcs, feeds=feeds, show_stats=show_stats, used_today=used_today,
           feed_groups=[g for g in feed_groups if g["feeds"]], src_index=src_index,
           n_episodes=sum(v["episodes"] for v in show_stats.values()), today=dates[0] if dates else None)
    render("about.html", "about.html", "", n_podcasts=len(srcs), n_feeds=len(feeds),
           arch=_arch_stats(root, data, items, hots), n_terms=len(glossary), n_lessons=sum(len(u["lessons"]) for u in json.loads(course_path.read_text())["units"]) if course_path.exists() else 0)
    render("play.html", "play.html", "")
    render("admin.html", "admin.html", "")
    render("scorecard.html", "scorecard.html", "", **_scorecard(data))
    course_path = data / "learn" / "course.json"
    course = json.loads(course_path.read_text()) if course_path.exists() else None
    lessons = [{**l, "unit": u["title"]} for u in course["units"] for l in u["lessons"]] if course else []
    practice_path = data / "learn" / "practice.json"
    practice = json.loads(practice_path.read_text()) if practice_path.exists() else None
    for l in lessons:
        l["slug"] = f"{l['id']}-" + re.sub(r"[^a-z0-9]+", "-", l["title"].lower()).strip("-")[:60]
    render("learn.html", "learn.html", "", course=course, lessons=lessons, practice=practice)
    for i, l in enumerate(lessons):  # one indexable page per lesson
        render("lesson.html", f"lessons/{l['slug']}.html", "../", l=l, total=len(lessons), all=lessons,
               next=lessons[i + 1] if i + 1 < len(lessons) else None)
    # Search engines: sitemap of every public page, and robots.txt pointing to it (admin stays out).
    urls = "".join(f"<url><loc>{u}</loc><lastmod>{m}</lastmod></url>" for u, m in pages)
    (out / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>'
                                     f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    # Short, branded link for the Android app: stocksplain.app/android → the newest GitHub release.
    rel = "https://github.com/litaPhsinaM/stocksplain/releases/latest"
    (out / "android").mkdir(exist_ok=True)
    (out / "android" / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>Stocksplain for Android</title>'
        f'<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url={rel}">'
        f'<script>location.replace("{rel}")</script><p>Opening the Stocksplain Android download… '
        f'<a href="{rel}">Tap here if nothing happens</a>.</p>')
    (out / "robots.txt").write_text(f"User-agent: *\nDisallow: /admin.html\nSitemap: {site_url}sitemap.xml\n")
    (out / "search.json").write_text(json.dumps(_search_index(items, hots, glossary, markets), separators=(",", ":")))
    old = root / "site.old"
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        final.rename(old)
    out.rename(final)
    shutil.rmtree(old, ignore_errors=True)
    print(f"Built site: {len(dates)} days, {len(items)} items, {len(glossary)} glossary terms → {final}/index.html")
