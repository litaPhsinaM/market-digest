"""Render saved summaries into a static site in ./site."""
import json
import shutil
from collections import defaultdict
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape


def _minutes(secs):
    return round((secs or 0) / 60)


def build(root: Path):
    data, out = root / "data", root / "site"
    items = [json.loads(p.read_text()) for p in sorted((data / "items").glob("*.json"))]
    briefs = {p.stem: json.loads(p.read_text()) for p in (data / "briefs").glob("*.json")}
    srcs = yaml.safe_load((root / "sources.yaml").read_text())["sources"]

    days = defaultdict(list)
    for it in items:
        days[it["digest_date"]].append(it)
    dates = sorted(days, reverse=True)

    glossary = {}
    for it in sorted(items, key=lambda i: i["digest_date"]):
        for t in it["summary"]["glossary"]:
            key = t["term"].strip().lower()
            entry = glossary.setdefault(key, {**t, "seen": []})
            entry["seen"].append({"date": it["digest_date"], "id": it["id"], "title": it["summary"]["headline"]})
    glossary = sorted(glossary.values(), key=lambda t: t["term"].lower())

    env = Environment(loader=FileSystemLoader(root / "templates"), autoescape=select_autoescape())
    env.filters["minutes"] = _minutes

    if out.exists():
        shutil.rmtree(out)
    (out / "days").mkdir(parents=True)
    shutil.copy(root / "templates" / "style.css", out / "style.css")

    def day_ctx(date):
        its = sorted(days[date], key=lambda i: (not i["summary"]["worth_reading"], i["source_name"]))
        return {"date": date, "brief": briefs.get(date), "items": its,
                "by_id": {i["id"]: i for i in its},
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
    render("sources.html", "sources.html", "", sources=srcs)
    print(f"Built site: {len(dates)} days, {len(items)} items, {len(glossary)} glossary terms → {out}/index.html")
