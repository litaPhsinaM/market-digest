"""Find new episodes/videos and fetch their text (captions) or audio."""
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

import feedparser

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) market-digest/0.1"
YTDLP = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings"]


@dataclass
class Item:
    id: str
    source_id: str
    source_name: str
    kind: str          # podcast | youtube
    title: str
    url: str           # human link (episode page / video)
    media_url: str     # mp3 for podcasts, video url for youtube
    published: str     # YYYY-MM-DD
    duration: int | None  # seconds

    def to_dict(self):
        return asdict(self)


def _parse_duration(raw) -> int | None:
    if not raw:
        return None
    parts = [int(p) for p in str(raw).split(":") if p.strip().isdigit()]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs or None


def list_podcast(src: dict, limit: int) -> list[Item]:
    feed = feedparser.parse(src["url"], agent=UA)
    items = []
    for e in feed.entries:
        if len(items) >= limit:
            break
        audio = next((l.href for l in e.get("enclosures", []) if "audio" in l.get("type", "audio")), None)
        if not audio:
            continue
        if re.search(r"\btrailer\b|\bintroducing\b", e.title, re.I):
            continue
        guid = e.get("id") or audio
        pub = e.get("published_parsed")
        items.append(Item(
            id=f"{src['id']}-{hashlib.sha1(guid.encode()).hexdigest()[:10]}",
            source_id=src["id"], source_name=src["name"], kind="podcast",
            title=e.title, url=e.get("link") or audio, media_url=audio,
            published=dt.date(*pub[:3]).isoformat() if pub else dt.date.today().isoformat(),
            duration=_parse_duration(e.get("itunes_duration")),
        ))
    return items


def list_youtube(src: dict, limit: int) -> list[Item]:
    # Scan a few extra so Shorts/livestreams can be skipped without starving the limit.
    out = subprocess.run(
        YTDLP + ["--flat-playlist", "--playlist-end", str(limit + 5),
                 "--print", "%(id)s\t%(duration)s\t%(title)s", src["url"]],
        capture_output=True, text=True, timeout=120,
    )
    items = []
    for line in out.stdout.splitlines():
        vid, dur, title = line.split("\t", 2)
        dur = int(float(dur)) if dur not in ("NA", "None", "") else None
        if dur is None or dur < 180 or dur > 2 * 3600:  # skip Shorts, streams, marathons
            continue
        items.append(Item(
            id=f"{src['id']}-{vid}", source_id=src["id"], source_name=src["name"], kind="youtube",
            title=title, url=f"https://www.youtube.com/watch?v={vid}",
            media_url=f"https://www.youtube.com/watch?v={vid}",
            published=dt.date.today().isoformat(), duration=dur,
        ))
        if len(items) >= limit:
            break
    return items


def list_source(src: dict, limit: int) -> list[Item]:
    return (list_podcast if src["kind"] == "podcast" else list_youtube)(src, limit)


def youtube_transcript(item: Item) -> str | None:
    """Return caption text (manual preferred, else auto) and fix the publish date. None if unavailable."""
    out = subprocess.run(YTDLP + ["-j", "--skip-download", item.media_url],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return None
    info = json.loads(out.stdout)
    if info.get("upload_date"):
        d = info["upload_date"]
        item.published = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    for pool in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang in ("en", "en-US", "en-GB", "en-orig"):
            track = next((t for t in pool.get(lang, []) if t.get("ext") == "json3"), None)
            if track:
                return _json3_to_text(_get(track["url"]))
    return None


def _json3_to_text(raw: bytes) -> str:
    words = []
    for ev in json.loads(raw).get("events", []):
        for seg in ev.get("segs") or []:
            words.append(seg.get("utf8", ""))
    text = re.sub(r"\s+", " ", "".join(words)).strip()
    return text


def download(url: str, dest: Path) -> Path:
    dest.write_bytes(_get(url, timeout=300))
    return dest


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
