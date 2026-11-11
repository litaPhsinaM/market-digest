"""Push trusted data to Supabase: prices (which fill paper-trading orders and settle predictions) and quiz answer keys.

Uses the database connection in .env (SUPABASE_DB_URL), or the API with SUPABASE_SECRET_KEY if that's all there is.
Neither is ever committed (.env is git-ignored). Without them this step is skipped; only the games miss new prices.
"""
import json
import os
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    url = (yaml.safe_load((ROOT / "sources.yaml").read_text()).get("supabase") or {}).get("url")
    return url, os.environ.get("SUPABASE_SECRET_KEY")


def _db_url():
    _env()
    if not os.environ.get("SUPABASE_DB_URL"):
        return None
    from migrate import db_url  # handles passwords with special characters
    return db_url()


def _key_ok(key) -> bool:
    return bool(key) and key.startswith("sb_secret_") and "..." not in key and "…" not in key


def available() -> bool:
    url, key = _env()
    return bool(_db_url() or (url and _key_ok(key)))


def _upsert_sql(table: str, rows: list[dict], conflict: str):
    import psycopg
    cols = list(rows[0])
    sql = (f"insert into public.{table} ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))}) "
           f"on conflict ({conflict}) do update set {', '.join(f'{c} = excluded.{c}' for c in cols if c not in conflict)}")
    with psycopg.connect(_db_url()) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, [[r[c] for c in cols] for r in rows])


def _post(table: str, rows: list[dict], upsert: bool = False):
    url, key = _env()
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}", data=json.dumps(rows).encode(), method="POST",
        headers={"apikey": key, "Content-Type": "application/json",
                 "Prefer": "return=minimal" + (",resolution=merge-duplicates" if upsert else "")},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def push_prices(snapshot: dict):
    """The database fills pending orders and scores predictions on any price stamped Mon-Fri 9:30-16:00 New York
    time (see the on_new_price trigger), so only send it prices that really are from today's session:
      - a symbol that hasn't traded today (holiday, halt, Yahoo gap) would fill orders at an old close: skipped;
      - on a holiday or after a 1 pm early close the trigger can't tell the market is shut: stale prices skipped;
      - after the close, today's prices are the closing prices: stamped at the close, so orders placed before
        the bell fill at the close and orders placed after it wait for the next open.
    """
    import datetime as dt
    import math
    import re
    from digest import hours
    as_of = dt.datetime.fromisoformat(snapshot["as_of"]).astimezone(hours.NY)
    today = as_of.date().isoformat()
    sess = hours.session(as_of.date())
    fresh_as_of = sess[1] if sess and as_of > sess[1] else as_of
    in_window = lambda t: t.weekday() < 5 and dt.time(9, 30) <= t.time() <= dt.time(16, 0)
    session_ok = lambda t: bool(sess) and sess[0] <= t <= sess[1]

    rows, seen, skipped = [], set(), 0
    quotes = (snapshot.get("indices", []) + snapshot.get("funds", []) + snapshot.get("companies", [])
              + snapshot.get("universe", []) + [m for g in (snapshot.get("movers") or {}).values() for m in g])
    for q in quotes:
        sym, price = q.get("symbol"), q.get("price")
        if sym in seen or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0 \
                or not re.fullmatch(r"[A-Z0-9.^=\-]{1,12}", sym or ""):
            continue  # one bad quote must not fail the whole batch (the table rejects it)
        seen.add(sym)
        fresh = q.get("date") is not None and q["date"] >= today
        t = fresh_as_of if fresh and not sym.endswith("-USD") else as_of  # crypto trades on after the bell
        if in_window(t) and not (fresh and session_ok(t)):
            skipped += 1
            continue
        rows.append({"symbol": sym, "as_of": t.isoformat(), "price": round(float(price), 4), "name": q.get("name")})
    if skipped:
        print(f"  {skipped} prices not from today's session, not sent (they'd fill orders at a stale price)")
    if not rows:
        return
    if _db_url():
        _upsert_sql("prices", rows, "symbol, as_of")
    else:
        _post("prices", rows, upsert=True)
    print(f"Pushed {len(rows)} prices to Supabase (fills pending orders, settles predictions)")


def push_quiz_keys(day: str, quiz: dict):
    rows = [{"day": day, "q": i, "answer": q["answer"]} for i, q in enumerate(quiz.get("questions", []))]
    if rows:
        if _db_url():
            _upsert_sql("quiz_keys", rows, "day, q")
        else:
            _post("quiz_keys", rows, upsert=True)
