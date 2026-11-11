"""Store the GitHub token for the database price timer (migration 015) in Supabase Vault, without printing it.
Put GITHUB_DISPATCH_TOKEN=github_pat_... in .env, then run: .venv/bin/python scripts/set-dispatch-token.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import psycopg  # noqa: E402
from migrate import db_url  # noqa: E402

env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
tok = env.get("GITHUB_DISPATCH_TOKEN", "").strip().strip('"')
if not tok.startswith(("github_pat_", "ghp_")):
    sys.exit("GITHUB_DISPATCH_TOKEN is missing from .env (it should start with github_pat_)")
with psycopg.connect(db_url(), autocommit=True) as c:
    c.execute("delete from vault.secrets where name = 'github_dispatch_token'")
    c.execute("select vault.create_secret(%s, 'github_dispatch_token', 'GitHub token for the price timer')", (tok,))
    c.execute("select public.dispatch_price_job()")
print("Saved. The database now starts the price job every 15 minutes in market hours (a test run was just sent).")
