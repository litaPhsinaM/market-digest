"""Apply supabase/migrations/*.sql to the database in SUPABASE_DB_URL (from .env), in order, once each.

  python migrate.py            # apply pending migrations
  python migrate.py --status   # list applied / pending
  python migrate.py --sql "select count(*) from public.events"   # run one read query (for checks)

Each migration runs in its own transaction: if anything fails, that migration is rolled back and we stop.
Applied migrations are recorded in public._migrations.
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote

import psycopg

ROOT = Path(__file__).parent
MIGRATIONS = ROOT / "supabase" / "migrations"


def db_url() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL is not set in .env")
    # Passwords pasted as-is may contain @ # / : etc. Split on the LAST "@" and percent-encode the password.
    m = re.match(r"^(postgres(?:ql)?://)([^:/]+):(.*)@([^@]+)$", url)
    if m:
        scheme, user, pw, rest = m.groups()
        url = f"{scheme}{user}:{quote(unquote(pw), safe='')}@{rest}"
    return url


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sql")
    args = ap.parse_args()

    with psycopg.connect(db_url(), autocommit=True) as conn:
        if args.sql:
            with conn.cursor() as cur:
                cur.execute(args.sql)
                if cur.description:
                    print(" | ".join(d.name for d in cur.description))
                    for row in cur.fetchall():
                        print(" | ".join(str(v) for v in row))
            return
        conn.execute("create table if not exists public._migrations (name text primary key, applied_at timestamptz default now())")
        conn.execute("alter table public._migrations enable row level security")  # not readable through the public API
        done = {r[0] for r in conn.execute("select name from public._migrations")}
        files = sorted(MIGRATIONS.glob("*.sql"))
        for f in files:
            state = "applied" if f.name in done else "pending"
            if args.status:
                print(f"{state:8} {f.name}")
                continue
            if f.name in done:
                continue
            print(f"applying {f.name} …", end=" ", flush=True)
            try:
                with conn.transaction():
                    conn.execute(f.read_text())
                    conn.execute("insert into public._migrations (name) values (%s)", (f.name,))
            except Exception as e:
                print("FAILED, rolled back")
                sys.exit(f"{type(e).__name__}: {e}")
            print("ok")


if __name__ == "__main__":
    main()
