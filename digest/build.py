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


def build(root: Path):
    # Build into a temporary folder and swap it in at the end, so the live site is never half-built,
    # and a failed build leaves the previous site untouched.
    data, final, out = root / "data", root / "site", root / "site.tmp"
    items = [json.loads(p.read_text()) for p in sorted((data / "items").glob("*.json"))]
    briefs = {p.stem: json.loads(p.read_text()) for p in (data / "briefs").glob("*.json")}
    cfg = yaml.safe_load((root / "sources.yaml").read_text())
    srcs, feeds = cfg["sources"], cfg.get("news", [])
    load = lambda sub: {p.stem: json.loads(p.read_text()) for p in (data / sub).glob("*.json")} if (data / sub).exists() else {}
    hots, quizzes, audio = load("hot"), load("quiz"), load("audio")

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
    glossary = sorted(glossary.values(), key=lambda t: t["term"].lower())

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
        return {"date": date, "brief": briefs.get(date), "items": its, "market": mkt, "hot": hots.get(date), "call_co": call_co,
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
    render("glossary.html", "glossary.html", "", terms=glossary)
    render("sources.html", "sources.html", "", sources=srcs, feeds=feeds)
    render("about.html", "about.html", "", n_podcasts=len(srcs), n_feeds=len(feeds))
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
