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
    rows, seen = [], set()
    as_of = snapshot["as_of"]
    for q in snapshot.get("indices", []) + snapshot.get("funds", []) + snapshot.get("companies", []):
        if q["symbol"] not in seen:
            seen.add(q["symbol"])
            rows.append({"symbol": q["symbol"], "as_of": as_of, "price": round(q["price"], 4), "name": q.get("name")})
    for q in snapshot.get("universe", []):
        if q["symbol"] not in seen:
            seen.add(q["symbol"])
            rows.append({"symbol": q["symbol"], "as_of": as_of, "price": round(q["price"], 4), "name": q["name"]})
    for group in (snapshot.get("movers") or {}).values():
        for m in group:
            if m["symbol"] not in seen and m.get("price"):
                seen.add(m["symbol"])
                rows.append({"symbol": m["symbol"], "as_of": as_of, "price": round(m["price"], 4), "name": m.get("name")})
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
