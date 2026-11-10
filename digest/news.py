"""Collect recent newsroom headlines (headline + the feed's own short blurb only) for 'What's hot'."""
import hashlib
import html
import re
import time

import feedparser

from digest.sources import UA

MAX_AGE_H = 30
PER_FEED = 15


def _clean(text: str, limit: int = 280) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def collect(feeds: list[dict]) -> list[dict]:
    cutoff = time.time() - MAX_AGE_H * 3600
    seen, out = set(), []
    for f in feeds:
        try:
            parsed = feedparser.parse(f["url"], agent=UA)
        except Exception as e:
            print(f"! news feed {f['name']}: {e}")
            continue
        n = 0
        for e in parsed.entries:
            pub = e.get("published_parsed") or e.get("updated_parsed")
            if not pub or time.mktime(pub) < cutoff or not e.get("link"):
                continue
            key = re.sub(r"\W+", "", e.title.lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "id": "h" + hashlib.sha1(e.link.encode()).hexdigest()[:8],
                "source": f["name"], "title": _clean(e.title, 200), "blurb": _clean(e.get("summary", "")),
                "url": e.link, "published": time.strftime("%Y-%m-%dT%H:%M", pub),
            })
            n += 1
            if n >= PER_FEED:
                break
    out.sort(key=lambda h: h["published"], reverse=True)
    return out
