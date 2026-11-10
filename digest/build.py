"""Render saved summaries into a static site in ./site."""
import datetime as dt
import json
import shutil
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


def build(root: Path):
    data, out = root / "data", root / "site"
    items = [json.loads(p.read_text()) for p in sorted((data / "items").glob("*.json"))]
    briefs = {p.stem: json.loads(p.read_text()) for p in (data / "briefs").glob("*.json")}
    cfg = yaml.safe_load((root / "sources.yaml").read_text())
    srcs, feeds = cfg["sources"], cfg.get("news", [])
    hots = {p.stem: json.loads(p.read_text()) for p in (data / "hot").glob("*.json")} if (data / "hot").exists() else {}

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
    glossary = sorted(glossary.values(), key=lambda t: t["term"].lower())

    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    env.filters["minutes"] = _minutes
    env.filters["num"] = _num
    env.filters["big"] = _big
    env.filters["qf"] = _quote_fmt
    env.filters["initials"] = _initials
    markets = {p.stem: json.loads(p.read_text()) for p in (data / "market").glob("*.json")}
    src_index = {s["id"]: n for n, s in enumerate(srcs)}

    if out.exists():
        shutil.rmtree(out)
    (out / "days").mkdir(parents=True)
    for asset in ("style.css", "app.js"):
        shutil.copy(root / "templates" / asset, out / asset)

    def day_ctx(date):
        its = sorted(days[date], key=lambda i: (not i["summary"]["worth_reading"], i["source_name"]))
        mkt = markets.get(date)
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
        return {"date": date, "brief": briefs.get(date), "items": its, "market": mkt, "hot": hots.get(date),
                "n_podcasts": len(srcs), "n_feeds": len(feeds),
                "by_id": {i["id"]: i for i in its}, "src_index": src_index,
                "pretty_date": dt.date.fromisoformat(date).strftime("%A, %B %-d, %Y"),
                "listen_min": sum(_minutes(i["duration"]) for i in its)}

    def render(name, path, prefix, **ctx):
        (out / path).write_text(env.get_template(name).render(prefix=prefix, **ctx))

    for i, date in enumerate(dates):
        nav = {"newer": dates[i - 1] if i else None, "older": dates[i + 1] if i + 1 < len(dates) else None}
        render("day.html", f"days/{date}.html", "../", **day_ctx(date), nav=nav)
    if dates:
        render("day.html", "index.html", "", **day_ctx(dates[0]),
               nav={"newer": None, "older": dates[1] if len(dates) > 1 else None}, is_home=True)
    else:
        render("empty.html", "index.html", "")
    render("archive.html", "archive.html", "",
           days=[{"date": d, **day_ctx(d)} for d in dates])
    render("glossary.html", "glossary.html", "", terms=glossary)
    render("sources.html", "sources.html", "", sources=srcs, feeds=feeds)
    render("about.html", "about.html", "", n_podcasts=len(srcs), n_feeds=len(feeds))
    print(f"Built site: {len(dates)} days, {len(items)} items, {len(glossary)} glossary terms → {out}/index.html")
